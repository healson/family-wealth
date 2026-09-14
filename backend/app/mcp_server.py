"""轻量 MCP Server：向外部 AI Agent 提供家庭财富数据查询/记账能力
支持两种模式：
  1. HTTP 模式（FastAPI 挂载于 /mcp）：AI Agent 通过 URL 连接，按 JWT 区分账号
  2. stdio 模式（python -m app.mcp_server）：Claude Desktop / Cursor 等本地 Agent 使用
协议：JSON-RPC 2.0 over SSE（HTTP）或 stdio
"""
import json
import os
import sys
from datetime import date, datetime

import jwt
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse, StreamingResponse

from .database import SessionLocal
from .models import (
    Account,
    Asset,
    Category,
    DailyPnl,
    InsurancePolicy,
    InvestmentAccount,
    Transaction,
    User,
)
from .auth import SECRET_KEY, JWT_ALGORITHM
from .utils import apply_txn_balance

# ---------------- 工具定义 ----------------
TOOLS = [
    {
        "name": "get_summary",
        "description": "获取家庭财富总览（总资产/净资产/负债/本月收支/资产构成）",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_assets",
        "description": "列出所有固定资产（房产/车辆等）及其估值",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_insurance",
        "description": "列出所有保单（保险公司/险种/保费/保额/到期日）",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_accounts",
        "description": "列出所有现金账户及余额",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_financial",
        "description": "列出所有投资账户及市值/今日盈亏/本月盈亏",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "query_financial_pnl",
        "description": "查询投资账户的按日盈亏记录（每天一条，正=盈利负=亏损），可按日期范围/账户过滤，返回按日汇总与明细",
        "inputSchema": {
            "type": "object",
            "properties": {
                "start": {"type": "string", "description": "开始日期 YYYY-MM-DD，如 2026-08-23"},
                "end": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
                "account_id": {"type": "integer", "description": "投资账户ID，可省略（查询全部账户）"},
            },
        },
    },
    {
        "name": "list_transactions",
        "description": "按时间倒序列出收支记录，可按月过滤",
        "inputSchema": {
            "type": "object",
            "properties": {
                "month": {"type": "string", "description": "YYYY-MM，如 2026-08，可省略"},
                "limit": {"type": "integer", "description": "返回条数，默认 50"},
            },
        },
    },
    {
        "name": "query_transactions",
        "description": "按关键词/类型/日期范围查询收支记录",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "备注或分类关键词"},
                "type": {"type": "string", "description": "收入或支出"},
                "start": {"type": "string", "description": "开始日期 YYYY-MM-DD"},
                "end": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
            },
        },
    },
    {
        "name": "add_transaction",
        "description": "新增一笔收支记录（必须指定 account_id，与页面「记一笔」一致：收入自动加账户余额、支出自动减账户余额）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "description": "收入或支出"},
                "amount": {"type": "number", "description": "金额（元）"},
                "account_id": {"type": "integer", "description": "现金账户ID（必填，可先用 list_accounts 查询），收支将自动增减该账户余额"},
                "category": {"type": "string", "description": "分类名，如 餐饮/交通，可省略"},
                "date": {"type": "string", "description": "日期 YYYY-MM-DD，默认今天"},
                "note": {"type": "string", "description": "备注"},
            },
            "required": ["type", "amount", "account_id"],
        },
    },
]


def _rows(rows):
    return json.dumps(rows, ensure_ascii=False, default=str)


def _tool_get_summary(db: Session, user_id: int):
    from .routers.dashboard import summary as dash_summary

    s = dash_summary(db=db, user=db.get(User, user_id))
    return {
        "总资产": s["total_assets"], "净资产": s["net_worth"], "负债": s["total_liabilities"],
        "本月收入": s["month_income"], "本月支出": s["month_expense"], "本月投资盈亏": s["month_pnl"],
        "资产构成": s["asset_breakdown"], "待缴费保单": len(s["insurance_expiring"]),
    }


def _tool_list_assets(db, uid):
    return [{"名称": a.name, "类别": a.category, "当前估值": float(a.current_value),
             "贷款余额": float(a.loan_balance), "净值": float(a.current_value) - float(a.loan_balance)}
            for a in db.query(Asset).filter(Asset.user_id == uid).all()]


def _tool_list_insurance(db, uid):
    return [{"保险公司": p.company, "产品": p.product_name, "险种": p.category,
             "保费": float(p.premium), "保额": float(p.coverage), "状态": p.status,
             "到期日": str(p.end_date or "")} for p in db.query(InsurancePolicy).filter(InsurancePolicy.user_id == uid).all()]


def _tool_list_accounts(db, uid):
    return [{"名称": a.name, "类型": a.type, "余额": float(a.balance)} for a in db.query(Account).filter(Account.user_id == uid).all()]


def _tool_list_financial(db, uid):
    from .routers.financial import _to_out as fin_out

    accounts = db.query(InvestmentAccount).filter(InvestmentAccount.user_id == uid).all()
    return [{"名称": a.name, "类型": a.type, "市值": float(a.balance),
             "今日盈亏": o.today_pnl, "本月盈亏": o.month_pnl} for a in accounts
            for o in [fin_out(a, db)]]


def _tool_query_financial_pnl(db, uid, start=None, end=None, account_id=None):
    """按日期范围查询投资账户日盈亏（daily_pnl）：正=盈利，负=亏损"""
    q = db.query(DailyPnl).filter(DailyPnl.user_id == uid)
    if account_id:
        q = q.filter(DailyPnl.account_id == account_id)
    if start:
        q = q.filter(DailyPnl.date >= date.fromisoformat(start))
    if end:
        q = q.filter(DailyPnl.date <= date.fromisoformat(end))
    rows = q.order_by(DailyPnl.date.desc()).all()
    if not rows:
        return {"提示": "该日期范围内没有投资日盈亏记录（可在「金融投资」页面给账户记盈亏后查询）", "记录": []}
    # 按日汇总（多账户合并）
    agg: dict[str, float] = {}
    for r in rows:
        d = str(r.date)
        agg[d] = agg.get(d, 0.0) + float(r.pnl)
    return {
        "按日汇总": [{"日期": d, "当日总盈亏": round(v, 2)} for d, v in sorted(agg.items(), reverse=True)],
        "明细": [{"日期": str(r.date), "账户ID": r.account_id, "盈亏": float(r.pnl), "备注": r.note} for r in rows],
    }


def _tool_list_transactions(db, uid, month=None, limit=50):
    q = db.query(Transaction).filter(Transaction.user_id == uid)
    if month:
        from sqlalchemy import func

        q = q.filter(func.strftime("%Y-%m", Transaction.date) == month)
    q = q.order_by(Transaction.date.desc()).limit(min(limit or 50, 200))
    return [{"日期": str(t.date), "类型": t.type, "金额": float(t.amount),
             "分类": t.category.name if t.category else None, "备注": t.note} for t in q.all()]


def _tool_query_transactions(db, uid, keyword=None, type=None, start=None, end=None):
    q = db.query(Transaction).filter(Transaction.user_id == uid)
    if type:
        q = q.filter(Transaction.type == type)
    if start:
        q = q.filter(Transaction.date >= date.fromisoformat(start))
    if end:
        q = q.filter(Transaction.date <= date.fromisoformat(end))
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(Transaction.note.like(like) | Transaction.category.has(Category.name.like(like)))
    q = q.order_by(Transaction.date.desc()).limit(100)
    return [{"日期": str(t.date), "类型": t.type, "金额": float(t.amount),
             "分类": t.category.name if t.category else None, "备注": t.note} for t in q.all()]


def _tool_add_transaction(db, uid, type, amount, account_id=None, category=None, date=None, note=None):
    if type not in ("收入", "支出"):
        return {"error": "type 必须为 收入 或 支出"}
    if float(amount or 0) <= 0:
        return {"error": "金额必须大于 0"}
    # 与 REST 接口一致：收支必须关联现金账户并联动余额，否则会产生「不守恒」的幽灵收支
    if not account_id:
        accounts = db.query(Account).filter(Account.user_id == uid).all()
        return {
            "error": "必须指定 account_id：收支需与现金账户强关联（收入加余额/支出减余额）",
            "可用账户": [{"id": a.id, "名称": a.name, "余额": float(a.balance)} for a in accounts],
        }
    account = db.query(Account).filter(Account.id == account_id, Account.user_id == uid).first()
    if account is None:
        return {"error": f"账户 {account_id} 不存在或不属于当前账号"}
    d = date and date.fromisoformat(date) or datetime.now().date()
    cat_id = None
    if category:
        cat = db.query(Category).filter(Category.user_id == uid, Category.name == category).first()
        if cat is None:
            cat = Category(user_id=uid, name=category, type=type)
            db.add(cat)
            db.flush()
        cat_id = cat.id
    t = Transaction(user_id=uid, type=type, amount=float(amount), category_id=cat_id,
                    date=d, account_id=account.id, note=note)
    db.add(t)
    db.flush()
    apply_txn_balance(db, t, 1)  # 收入 + / 支出 −，同步账户余额
    db.commit()
    return {"ok": True, "id": t.id, "日期": str(d), "类型": type, "金额": float(amount),
            "账户": account.name, "账户余额": float(account.balance)}


TOOL_FUNCS = {
    "get_summary": _tool_get_summary,
    "list_assets": _tool_list_assets,
    "list_insurance": _tool_list_insurance,
    "list_accounts": _tool_list_accounts,
    "list_financial": _tool_list_financial,
    "query_financial_pnl": _tool_query_financial_pnl,
    "list_transactions": _tool_list_transactions,
    "query_transactions": _tool_query_transactions,
    "add_transaction": _tool_add_transaction,
}


def _resolve_user(token: str | None):
    """从 Bearer token 解析用户；无效/缺省时回退 admin"""
    db = SessionLocal()
    try:
        if token and token != "null":
            try:
                payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
                u = db.get(User, int(payload["sub"]))
                if u:
                    return u
            except jwt.PyJWTError:
                pass
        # 允许通过 MCP_TOKEN 环境变量做简单鉴权
        mcp_token = os.environ.get("MCP_TOKEN", "")
        if mcp_token and token != mcp_token:
            raise PermissionError("MCP_TOKEN 不匹配")
        return db.query(User).filter(User.username == os.environ.get("MCP_USERNAME", "admin")).first()
    finally:
        db.close()


def _call_tool(name: str, args: dict, user_id: int):
    db = SessionLocal()
    try:
        fn = TOOL_FUNCS.get(name)
        if fn is None:
            return {"error": f"未知工具: {name}"}
        result = fn(db, user_id, **args) if name in ("list_transactions", "query_transactions", "add_transaction", "query_financial_pnl") else fn(db, user_id)
        return result
    except Exception as e:
        return {"error": str(e)}
    finally:
        db.close()


def _handle_message(msg: dict, user_id: int) -> dict | None:
    method = msg.get("method")
    msg_id = msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "family-wealth-mcp", "version": "1.6.0"},
        }}
    if method == "notifications/initialized" or method == "ping":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params", {})
        result = _call_tool(params.get("name", ""), params.get("arguments", {}) or {}, user_id)
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "content": [{"type": "text", "text": _rows(result)}],
            "isError": False,
        }}
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"未知方法 {method}"}}


# ---------------- HTTP 模式（直接挂载到 FastAPI） ----------------
from starlette.requests import Request


async def mcp_sse_endpoint(request: Request):
    """GET /mcp：SSE 握手（旧版 MCP SSE 客户端）"""
    user = _resolve_user(_bearer(request))
    async def event_gen():
        yield 'event: endpoint\ndata: /mcp/message?user_id=%d\n\n' % user.id
        yield 'event: initialized\ndata: {}\n\n'
    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


async def mcp_post_endpoint(request: Request):
    """POST /mcp：streamable HTTP 风格 JSON-RPC（新版 MCP 客户端）"""
    user = _resolve_user(_bearer(request))
    try:
        msg = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32700, "message": "解析失败"}}, status_code=400)
    resp = _handle_message(msg, user.id)
    if resp is None:
        return JSONResponse({})
    return JSONResponse(resp)


async def mcp_message_endpoint(request: Request):
    """POST /mcp/message：SSE 客户端的 JSON-RPC 消息端点"""
    user_id = int(request.query_params.get("user_id", 1))
    try:
        msg = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32700, "message": "解析失败"}}, status_code=400)
    resp = _handle_message(msg, user_id)
    if resp is None:
        return JSONResponse({})
    return JSONResponse(resp)


def _bearer(request):
    from starlette.requests import Request

    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


# ---------------- stdio 模式 ----------------
def run_stdio():
    """python -m app.mcp_server 时运行（Claude Desktop / Cursor 等配置）"""
    user = _resolve_user(None)
    user_id = user.id if user else 1
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            msg = json.loads(line)
            resp = _handle_message(msg, user_id)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError:
            continue


if __name__ == "__main__":
    run_stdio()
