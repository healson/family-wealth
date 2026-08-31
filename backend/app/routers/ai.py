"""AI 分析对话：OpenAI 兼容接口（支持 OpenAI / DeepSeek / 通义 / 本地 Ollama）
配置优先级：账号级（ai_settings 表，页面可视化设置）> 环境变量（AI_API_KEY/AI_BASE_URL/AI_MODEL）
"""
import json
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import (
    AISetting,
    Account,
    Asset,
    Category,
    DailyPnl,
    InsurancePolicy,
    InvestmentAccount,
    Transaction,
    User,
)

router = APIRouter(
    prefix="/api/ai",
    tags=["AI 助手"],
    dependencies=[Depends(get_current_user)],
)

# 环境变量默认值（无数据库配置时回退）
ENV_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
ENV_API_KEY = os.environ.get("AI_API_KEY", "")
ENV_MODEL = os.environ.get("AI_MODEL", "gpt-4o-mini")


class ChatRequest(BaseModel):
    messages: list  # [{"role":"user|assistant","content":"..."}]
    question: str = ""


class AIConfigRequest(BaseModel):
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"


def get_ai_config(db: Session, user_id: int) -> dict:
    """获取账号的有效 AI 配置（数据库优先，环境变量兜底）"""
    setting = db.query(AISetting).filter(AISetting.user_id == user_id).first()
    if setting and setting.api_key:
        return {"base_url": setting.base_url.rstrip("/"), "api_key": setting.api_key, "model": setting.model}
    return {"base_url": ENV_BASE_URL, "api_key": ENV_API_KEY, "model": ENV_MODEL}


def _build_context(db: Session, user_id: int) -> str:
    """将当前账号的财务数据组装成上下文"""
    from .dashboard import summary as dashboard_summary

    try:
        s = dashboard_summary(db=db, user=db.get(User, user_id))
        context = f"""【家庭财富总览】
总资产:{s['total_assets']}元, 净资产:{s['net_worth']}元, 负债:{s['total_liabilities']}元
本月收入:{s['month_income']}元, 本月支出:{s['month_expense']}元, 本月投资盈亏:{s['month_pnl']}元
应收款(借出未还):{s.get('receivable', 0)}元, 应付款(借入未还):{s.get('payable', 0)}元
资产构成: {json.dumps(s['asset_breakdown'], ensure_ascii=False)}"""
    except Exception:
        context = "【家庭财富总览】暂无数据"
    lines = [context]

    assets = db.query(Asset).filter(Asset.user_id == user_id).all()
    if assets:
        lines.append("【固定资产】" + "; ".join(
            f"{a.name}({a.category}): 估值{a.current_value}元" for a in assets[:20]))
    policies = db.query(InsurancePolicy).filter(InsurancePolicy.user_id == user_id).all()
    if policies:
        lines.append("【保单】" + "; ".join(
            f"{p.company}-{p.product_name}: 保费{p.premium}/年, 保额{p.coverage}" for p in policies[:20]))
    accounts = db.query(Account).filter(Account.user_id == user_id).all()
    if accounts:
        lines.append("【现金账户】" + "; ".join(f"{a.name}: {a.balance}元" for a in accounts[:20]))
    invs = db.query(InvestmentAccount).filter(InvestmentAccount.user_id == user_id).all()
    if invs:
        lines.append("【投资账户】" + "; ".join(f"{a.name}: {a.balance}元" for a in invs[:20]))
    # 投资日盈亏（按天，正=盈利负=亏损）——支持「某天盈亏」类问题
    pnls = db.query(DailyPnl).filter(DailyPnl.user_id == user_id)\
        .order_by(DailyPnl.date.desc()).limit(90).all()
    if pnls:
        acct_map = {a.id: a.name for a in invs}
        lines.append("【投资日盈亏(按天)】" + "; ".join(
            f"{p.date} {acct_map.get(p.account_id, f'账户{p.account_id}')} {p.pnl}元" + (f"({p.note})" if p.note else "")
            for p in pnls))
    recent = db.query(Transaction).filter(Transaction.user_id == user_id)\
        .order_by(Transaction.date.desc()).limit(20).all()
    if recent:
        lines.append("【最近收支】" + "; ".join(
            f"{t.date} {t.type}{t.amount}元({t.category.name if t.category else '未分类'})" for t in recent))
    cats = db.query(Category).filter(Category.user_id == user_id).all()
    if cats:
        lines.append("【自定义分类】" + ",".join(c.name for c in cats[:50]))
    return "\n".join(lines)


@router.get("/config")
def ai_config(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """返回 AI 配置状态（不泄露密钥）"""
    setting = db.query(AISetting).filter(AISetting.user_id == user.id).first()
    cfg = get_ai_config(db, user.id)
    return {
        "configured": bool(cfg["api_key"]),
        "base_url": cfg["base_url"],
        "model": cfg["model"],
        "has_key": bool(cfg["api_key"]),
        "from_db": bool(setting and setting.api_key),
        "db_base_url": setting.base_url if setting else None,
        "db_model": setting.model if setting else None,
    }


@router.post("/config")
def save_ai_config(body: AIConfigRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """保存当前账号的 AI 模型配置"""
    base_url = body.base_url.strip().rstrip("/")
    model = body.model.strip()
    if not base_url or not model:
        raise HTTPException(status_code=400, detail="服务地址和模型名不能为空")
    if not base_url.startswith("http"):
        raise HTTPException(status_code=400, detail="服务地址需以 http:// 或 https:// 开头")
    setting = db.query(AISetting).filter(AISetting.user_id == user.id).first()
    if setting is None:
        setting = AISetting(user_id=user.id)
        db.add(setting)
    setting.base_url = base_url
    setting.model = model
    # 留空 api_key 表示保留原有（或清空需显式传 'clear'）
    if body.api_key:
        setting.api_key = body.api_key.strip()
    elif body.api_key == "clear":
        setting.api_key = None
    db.commit()
    return {"ok": True, "message": "AI 模型配置已保存"}


@router.post("/chat")
def chat(body: ChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """AI 对话：结合当前账号财务数据回答用户问题"""
    cfg = get_ai_config(db, user.id)
    if not cfg["api_key"]:
        raise HTTPException(
            status_code=400,
            detail="尚未配置 AI 服务。请点击页面右上角「⚙ 模型设置」配置服务地址与密钥（支持 OpenAI / DeepSeek / 通义 / 本地 Ollama）。",
        )
    context = _build_context(db, user.id)
    system = (
        "你是家庭财富管理助手，帮助用户分析家庭财务。以下是用当前账号实时数据生成的信息：\n"
        f"{context}\n\n"
        "请基于这些数据回答用户的问题；数据未覆盖时请说明。回答使用简体中文，简洁、有数据支撑，可给出建议。"
    )
    messages = [{"role": "system", "content": system}] + body.messages
    if body.question:
        messages.append({"role": "user", "content": body.question})

    try:
        resp = httpx.post(
            f"{cfg['base_url']}/chat/completions",
            headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
            json={"model": cfg["model"], "messages": messages, "temperature": 0.3, "max_tokens": 1500},
            timeout=90,
        )
        resp.raise_for_status()
        data = resp.json()
        reply = data["choices"][0]["message"]["content"]
        return {"reply": reply}
    except httpx.HTTPStatusError as e:
        detail = f"AI 服务返回错误（HTTP {e.response.status_code}）：{e.response.text[:200]}"
        raise HTTPException(status_code=502, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI 服务连接失败：{e}")
