"""支付宝 / 微信支付 / 云闪付 / 京东支付 / 多多支付 账单导入"""
import csv
import io
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Account, Category, Transaction, User
from ..utils import apply_txn_balance

router = APIRouter(
    prefix="/api/import",
    tags=["账单导入"],
    dependencies=[Depends(get_current_user)],
)

PLATFORMS = ["支付宝", "微信支付", "云闪付", "京东支付", "多多支付"]

# 关键词 → 默认分类
_CATEGORY_KEYWORDS = [
    ("餐饮", ["美团", "餐厅", "餐饮", "外卖", "饿了么", "麦当劳", "肯德基", "星巴克", "奶茶", "食堂", "烧烤", "火锅"]),
    ("交通", ["滴滴", "地铁", "公交", "加油", "中石化", "中石油", "高速", "停车", "打车", "铁路", "航空"]),
    ("购物", ["淘宝", "天猫", "京东", "拼多多", "超市", "便利店", "商城", "优衣库", "耐克", "无印良品"]),
    ("居住", ["房租", "水电", "物业", "燃气", "宽带", "供暖"]),
    ("医疗", ["医院", "诊所", "药房", "药店", "挂号"]),
    ("教育", ["教育", "培训", "学费", "网课", "书店", "知网"]),
    ("娱乐", ["电影", "游戏", "KTV", "视频", "音乐", "腾讯视频", "爱奇艺", "B站"]),
    ("人情往来", ["红包", "转账", "礼金", "随礼"]),
    ("其他支出", []),
]
_INCOME_KEYWORDS = [("工资收入", ["工资", "薪金", "代发"]), ("理财收益", ["收益", "利息", "分红", "赎回"]), ("其他收入", [])]


def _match_category(text: str, ttype: str) -> str:
    if ttype == "收入":
        for name, kws in _INCOME_KEYWORDS:
            if any(k in text for k in kws):
                return name
        return "其他收入"
    for name, kws in _CATEGORY_KEYWORDS:
        if any(k in text for k in kws):
            return name
    return "其他支出"


def _parse_amount(v: str) -> float:
    """金额清洗：去掉 ¥/, 元 等字符；处理负数/带收支符号"""
    s = str(v or "").replace("¥", "").replace("￥", "").replace(",", "").replace("元", "").strip()
    if s in ("", "-"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        m = re.search(r"-?\d+(\.\d+)?", s)
        return float(m.group()) if m else 0.0


def _parse_date(v: str):
    """解析 2026-08-20 12:34:56 / 2026/08/20 / 20260820 等日期"""
    s = str(v or "").strip().replace("/", "-")
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(\d{4})(\d{2})(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def _read_rows(text: str):
    """尝试多种编码/分隔符读取表格行"""
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            content = text.encode("utf-8", errors="ignore").decode(enc) if enc != "utf-8-sig" else text
            if enc == "utf-8-sig":
                content = text
            reader = csv.reader(io.StringIO(content))
            return [r for r in reader if r and any(c.strip() for c in r)]
        except Exception:
            continue
    # 兜底：按行切分
    return [line.strip().split(",") for line in text.splitlines() if line.strip()]


def _find_col(row, *keywords):
    """按关键词在表头行中定位列索引。

    注意：关键词优先级高于列顺序——必须先把所有关键词按优先级扫一遍，
    否则「交易类型」列（微信账单第 2 列）会抢在「收/支」列前面被命中，
    导致收入行被误判为支出。
    """
    for kw in keywords:
        for i, cell in enumerate(row):
            if kw in str(cell).strip():
                return i
    return -1


def _smart_parse(text: str, platform: str):
    """通用解析：定位表头行 → 匹配日期/金额/收支/备注列 → 提取记录"""
    rows = _read_rows(text)
    # 找表头行（含"时间"或"金额"的行）
    header_idx = -1
    for i, r in enumerate(rows[:15]):
        joined = "".join(str(c) for c in r)
        if ("时间" in joined or "日期" in joined) and ("金额" in joined):
            header_idx = i
            break
    if header_idx == -1:
        raise HTTPException(status_code=400, detail=f"无法识别{platform}账单格式，请确认导出的账单文件类型")
    header = rows[header_idx]
    col_date = _find_col(header, "交易时间", "交易日期", "时间", "日期")
    col_amount = _find_col(header, "金额")
    col_type = _find_col(header, "收/支", "收支", "交易类型", "收/付", "资金流向")
    col_name = _find_col(header, "交易对方", "对方", "商户", "商品", "描述", "说明", "备注")
    if col_date == -1 or col_amount == -1:
        raise HTTPException(status_code=400, detail=f"{platform}账单缺少必要的列（日期/金额）")

    records = []
    for r in rows[header_idx + 1:]:
        if len(r) <= max(col_date, col_amount):
            continue
        d = _parse_date(r[col_date] if col_date < len(r) else "")
        if not d:
            continue
        amount = _parse_amount(r[col_amount] if col_amount < len(r) else "")
        if amount == 0:
            continue
        # 判定收支类型
        ttype = "支出"
        if col_type != -1 and col_type < len(r):
            tcell = str(r[col_type]).strip()
            # 「不计收支」= 余额宝/零钱通申赎、账户互转、还信用卡等内部资金移动，
            # 不属于家庭收入或支出；若当作支出导入会凭空扣减账户余额并虚增支出统计。
            if "不计" in tcell:
                continue
            if "收" in tcell and "支" not in tcell:
                ttype = "收入"
            elif "退款" in tcell or "返还" in tcell or "转入" in tcell:
                ttype = "收入"
        # 微信金额列可能带负号
        if amount < 0:
            amount = abs(amount)
            ttype = "支出" if ttype != "收入" else ttype
        # 若金额列本身为负且收支列未标注，则支出
        note = " ".join(str(c) for c in r[:5] if str(c).strip()).strip()
        name = str(r[col_name]).strip() if col_name != -1 and col_name < len(r) else note
        records.append({
            "date": d,
            "type": ttype,
            "amount": round(amount, 2),
            "category": _match_category(name, ttype),
            "note": name[:80],
            "platform": platform,
        })
    return records


class BillParseRequest(BaseModel):
    platform: str
    content: str  # 账单文件文本内容


@router.post("/bills/parse")
def parse_bill(body: BillParseRequest, user: User = Depends(get_current_user)):
    """解析账单文件，返回解析结果（预览用）"""
    if body.platform not in PLATFORMS:
        raise HTTPException(status_code=400, detail="不支持的平台")
    try:
        records = _smart_parse(body.content, body.platform)
    except HTTPException:
        raise
    if not records:
        raise HTTPException(status_code=400, detail="未能从账单中解析出有效记录，请检查文件内容")
    return {"count": len(records), "records": records[:500]}


class BillConfirmRequest(BaseModel):
    records: list  # [{"date","type","amount","category","note","platform"}]
    account_name: str = "支付宝"  # 记账到哪个现金账户


@router.post("/bills/confirm")
def confirm_bill(body: BillConfirmRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """确认导入：将解析结果写入日常收支"""
    if not body.records:
        raise HTTPException(status_code=400, detail="没有可导入的记录")
    account = db.query(Account).filter(
        Account.user_id == user.id, Account.name == body.account_name
    ).first()
    if account is None:
        account = Account(user_id=user.id, name=body.account_name, type="活期存款", balance=0,
                          note=f"由{body.account_name}账单导入自动创建")
        db.add(account)
        db.flush()

    imported = 0
    for rec in body.records:
        if not isinstance(rec, dict) or not rec.get("date") or not rec.get("amount"):
            continue
        cat = db.query(Category).filter(
            Category.user_id == user.id, Category.name == rec.get("category", ""),
            Category.type == rec.get("type", "支出"),
        ).first()
        if cat is None:
            cat = Category(user_id=user.id, name=rec.get("category", "其他支出"), type=rec.get("type", "支出"))
            db.add(cat)
            db.flush()
        try:
            d = datetime.strptime(rec["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        platform = rec.get("platform", "")
        note = f"{platform}{('·' + rec['note']) if rec.get('note') else ''}"
        txn = Transaction(
            user_id=user.id, type=rec.get("type", "支出"), amount=float(rec["amount"]),
            category_id=cat.id, date=d, account_id=account.id, note=note[:200],
        )
        db.add(txn)
        apply_txn_balance(db, txn, 1)  # 导入的收支同步账户余额
        imported += 1
    db.commit()
    return {"ok": True, "message": f"成功导入 {imported} 条记录", "imported": imported}
