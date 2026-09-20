import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from .models import Account

MONEY_FIELDS = {
    "purchase_price": float,
    "current_value": float,
    "loan_balance": float,
    "premium": float,
    "coverage": float,
    "balance": float,
    "amount": float,
    "quantity": float,
    "cost_price": float,
    "current_price": float,
    "price": float,
    "fee": float,
    "value": float,
}


def coerce_money(data: dict) -> dict:
    """将传入的金额字段安全转为 float，避免字符串/None 干扰"""
    result = dict(data)
    for field, cast in MONEY_FIELDS.items():
        if field in result and result[field] is not None:
            try:
                result[field] = cast(result[field])
            except (TypeError, ValueError):
                result[field] = 0
    return result


def jsonable(v):
    """把列值转成 `json.dumps` 能处理的形式。

    必须统一处理两类值，否则 `json.dump` 会直接抛 TypeError：
      · **Decimal** —— 所有 `Numeric(18,2)` 金额列取回来都是 Decimal，
        而标准库 json 不认它（JSON 导出、删除归档、自动备份都踩过）；
      · **date / datetime** —— 转 ISO 字符串。
    其余类型（bool/int/float/str/None）原样返回，非预期的类型退化为 str 而不是抛异常。
    """
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return str(v)


def days_until(target: date | None) -> int | None:
    if target is None:
        return None
    return (target - date.today()).days


def last_n_months(n: int = 12):
    """返回最近 n 个月的 (年, 月) 列表，从旧到新"""
    months = []
    now = datetime.now()
    for i in range(n - 1, -1, -1):
        m = now.month - i
        y = now.year
        while m <= 0:
            m += 12
            y -= 1
        months.append((y, m))
    return months


def apply_txn_balance(db: Session, txn, sign: int = 1):
    """收支记录联动账户余额（强关联）：
    - 收入：账户余额 + 金额；支出：账户余额 − 金额
    - sign=1 应用该笔影响；sign=-1 回滚（删除/修改前）
    无账户关联或金额为空的记录不联动。
    """
    account_id = getattr(txn, "account_id", None)
    amount = getattr(txn, "amount", None)
    ttype = getattr(txn, "type", None)
    if not account_id or amount is None or ttype not in ("收入", "支出"):
        return
    account = db.get(Account, account_id)
    if account is None:
        return
    delta = float(amount) * (1 if ttype == "收入" else -1) * sign
    account.balance = float(account.balance or 0) + delta


def apply_account_delta(db: Session, account_id: int | None, delta: float):
    """直接增减账户余额（用于借款/保单/资产/投资等模块的强关联）"""
    if not account_id or not delta:
        return
    account = db.get(Account, account_id)
    if account is None:
        return
    account.balance = float(account.balance or 0) + delta


def asset_cash_paid(asset) -> float:
    """固定资产购入实际从付款账户支出的现金 = 购入价 − 贷款余额（不低于 0）。

    贷款部分是银行直接付给卖方的，从未经过家庭账户，故不计入账户支出。
    该口径同时用于：账户余额扣减、资金流水展示、总览「资产购入」流向统计，
    三处必须一致，否则余额对账会出现差异。
    """
    price = float(getattr(asset, "purchase_price", 0) or 0)
    loan = float(getattr(asset, "loan_balance", 0) or 0)
    return max(price - loan, 0.0)


# ============================================================================
# 资金动作口径注册表
# ============================================================================
# 这是「哪些表会移动现金账户余额」的**唯一声明**。
#
# 为什么要有它：`collect_account_flows` 是全部余额对账与资金流水的唯一口径，
# 新增一类资金动作时若忘了在这里登记（也就忘了在 collect_account_flows 里取数），
# 后果是**这笔钱在流水与对账里完全消失** —— 不报错、只是账不平，
# 而且往往几个月后才被发现。
#
# 守它的测试：`backend/tests/test_flow_registry.py`
#   —— 扫 SQLAlchemy metadata，凡持有账户列的表必须在
#      FLOW_SOURCES ∪ FLOW_EXEMPT_TABLES 里，否则 FAIL。
#      新加资金动作模型却忘了登记，CI 就会拦下来。
FLOW_SOURCES = [
    {"kind": "收支", "table": "transactions", "account_columns": ["account_id"],
     "sign": "type=收入 则 +，支出 则 −"},
    {"kind": "存取", "table": "account_transactions", "account_columns": ["account_id"],
     "sign": "type=存入 则 +，取出 则 −"},
    {"kind": "转账", "table": "transfers", "account_columns": ["from_account_id", "to_account_id"],
     "sign": "本方是 from 则 −，是 to 则 +（一条记录产生两个方向的流水）"},
    {"kind": "借款", "table": "loans", "account_columns": ["account_id"],
     "sign": "type=借出 则 −，借入 则 +"},
    {"kind": "借款", "table": "loan_payments", "account_columns": ["account_id"],
     "sign": "父借款为借出 → 收款 +；为借入 → 还款 −"},
    {"kind": "保单", "table": "policy_payments", "account_columns": ["account_id"],
     "fallback": "insurance_policies.account_id（仅存量旧数据）", "sign": "恒 −（支出）"},
    {"kind": "资产", "table": "assets", "account_columns": ["account_id"],
     "sign": "−（购入价 − 贷款余额，贷款部分不经家庭账户）"},
    {"kind": "投资", "table": "investment_flows", "account_columns": ["cash_account_id"],
     "fallback": "investment_accounts.cash_account_id（仅存量旧数据）", "sign": "type=转入 则 −，转出 则 +"},
]

# 持有账户列但**本身不产生资金流水**的配置类/引用类表：显式豁免，改这里必须人工复核。
# 由 test_flow_registry.py 守门 —— 新出现的、持有账户列却没归类的表会让测试 FAIL。
FLOW_EXEMPT_TABLES = {
    "transaction_templates": "交易模板：只存默认账户，本身不产生资金流水",
    "scheduled_transactions": "定时交易：到期执行时才生成 transactions，本身不是流水",
    "investment_accounts": "投资账户：cash_account_id 是当前关联，历史归属以 investment_flows 快照为准",
    "insurance_policies": "保单：account_id 是当前缴费账户，历史缴费归属以 policy_payments 快照为准",
    "daily_pnl": "投资日盈亏：account_id 指向**投资账户**（非现金账户），盈亏不移动现金余额",
}


def collect_account_flows(db: Session, account_id: int, user_id: int) -> list[dict]:
    """收集某账户相关的全部资金动作（统一口径，供资金流水展示与余额对账使用）。

    这是**全部资金流水与余额对账的唯一口径**。取数来源必须与上方 `FLOW_SOURCES`
    注册表一一对应 —— 新增一类资金动作时两处都要改，`test_flow_registry.py` 会拦。

    返回 [{date, kind, title, amount, note, ref_type, ref_id, ref_parent_id}]，
    amount 为正表示资金流入该账户，负为流出；
    ref_type/ref_id/ref_parent_id 用于定位来源记录（前端删除/跳转）。
    """
    from .models import (
        AccountTransaction,
        Asset,
        InsurancePolicy,
        InvestmentAccount,
        InvestmentFlow,
        Loan,
        LoanPayment,
        Transaction,
        Transfer,
    )

    rows = []
    # 收支
    for t in db.query(Transaction).filter(Transaction.account_id == account_id, Transaction.user_id == user_id).all():
        rows.append({
            "date": t.date.isoformat(), "kind": "收支",
            "title": f"{t.type} · {t.category.name if t.category else '未分类'}",
            "amount": round(float(t.amount), 2) * (1 if t.type == "收入" else -1),
            "note": t.note,
            "ref_type": "transaction", "ref_id": t.id, "ref_parent_id": None,
        })
    # 存取
    for t in db.query(AccountTransaction).filter(AccountTransaction.account_id == account_id, AccountTransaction.user_id == user_id).all():
        rows.append({
            "date": t.date.isoformat(), "kind": "存取", "title": t.type,
            "amount": round(float(t.amount), 2) * (1 if t.type == "存入" else -1),
            "note": t.note,
            "ref_type": "account_transaction", "ref_id": t.id, "ref_parent_id": None,
        })
    # 转账
    transfers = db.query(Transfer).filter(
        Transfer.user_id == user_id,
        (Transfer.from_account_id == account_id) | (Transfer.to_account_id == account_id),
    ).all()
    for t in transfers:
        if t.from_account_id == account_id:
            rows.append({"date": t.date.isoformat(), "kind": "转账", "title": f"转出 → {t.to_account.name if t.to_account else '?'}", "amount": -round(float(t.amount), 2), "note": t.note, "ref_type": "transfer", "ref_id": t.id, "ref_parent_id": None})
        else:
            rows.append({"date": t.date.isoformat(), "kind": "转账", "title": f"转入 ← {t.from_account.name if t.from_account else '?'}", "amount": round(float(t.amount), 2), "note": t.note, "ref_type": "transfer", "ref_id": t.id, "ref_parent_id": None})
    # 借款本金
    for l in db.query(Loan).filter(Loan.account_id == account_id, Loan.user_id == user_id).all():
        rows.append({
            "date": l.date.isoformat(), "kind": "借款",
            "title": f"{l.type} · {l.counterparty}",
            "amount": -round(float(l.amount), 2) if l.type == "借出" else round(float(l.amount), 2),
            "note": l.note,
            "ref_type": "loan", "ref_id": l.id, "ref_parent_id": None,
        })
    # 借款收款/还款
    for p in db.query(LoanPayment).filter(LoanPayment.account_id == account_id, LoanPayment.user_id == user_id).all():
        loan = p.loan
        act = "收款" if loan and loan.type == "借出" else "还款"
        rows.append({
            "date": p.date.isoformat(), "kind": "借款",
            "title": f"{act} · {loan.counterparty if loan else '?'}",
            "amount": round(float(p.amount), 2) if act == "收款" else -round(float(p.amount), 2),
            "note": p.note,
            "ref_type": "loan_payment", "ref_id": p.id,
            "ref_parent_id": loan.id if loan else None,
        })
    # 保单缴费记录（每次缴费一条，历史留痕不可删除）
    from .models import PolicyPayment

    payments = db.query(PolicyPayment).join(InsurancePolicy, PolicyPayment.policy_id == InsurancePolicy.id)\
        .filter(PolicyPayment.user_id == user_id).all()
    for p in payments:
        # 归属账户优先用「本笔缴费账户快照」；存量旧数据无快照时回退到保单当前缴费账户。
        # 若用保单当前账户反推，改过缴费账户后历史缴费会被整体重新归属 → 对账失衡。
        owner = p.account_id or (p.policy.account_id if p.policy else None)
        if owner != account_id:
            continue
        rows.append({
            "date": p.date.isoformat(), "kind": "保单",
            "title": f"缴费 · {p.policy.product_name if p.policy else '保单'}",
            "amount": -round(float(p.amount), 2),
            "note": p.note,
            "ref_type": "policy_payment", "ref_id": p.id,
            "ref_parent_id": p.policy_id,
        })
    # 固定资产购入（仅「全款部分」走账户，贷款部分不经账户）
    for a in db.query(Asset).filter(Asset.account_id == account_id, Asset.user_id == user_id).all():
        cash_paid = asset_cash_paid(a)
        if cash_paid <= 0:
            continue
        d = (a.purchase_date or a.created_at.date()).isoformat()
        rows.append({"date": d, "kind": "资产", "title": f"购入 · {a.name}", "amount": -round(cash_paid, 2), "note": a.note, "ref_type": "asset", "ref_id": a.id, "ref_parent_id": None})
    # 投资转入/转出（现金账户视角）
    inv_map = {
        x.id: x for x in db.query(InvestmentAccount).filter(InvestmentAccount.user_id == user_id).all()
    }
    if inv_map:
        for f in db.query(InvestmentFlow).filter(
            InvestmentFlow.investment_account_id.in_(list(inv_map)), InvestmentFlow.user_id == user_id
        ).all():
            inv = inv_map.get(f.investment_account_id)
            # 归属账户优先用「本笔现金账户快照」；存量旧数据无快照时回退到投资账户当前关联。
            # 若用当前关联反推，改过关联现金账户后历史流水会被整体重新归属 → 对账失衡。
            owner = f.cash_account_id or (inv.cash_account_id if inv else None)
            if owner != account_id:
                continue
            rows.append({
                "date": f.date.isoformat(), "kind": "投资",
                "title": f"{f.type} · {inv.name if inv else '投资'}",
                "amount": -round(float(f.amount), 2) if f.type == "转入" else round(float(f.amount), 2),
                "note": f.note,
                "ref_type": "investment_flow", "ref_id": f.id,
                "ref_parent_id": f.investment_account_id,
            })
    return rows


# ============================================================================
# 余额对账（唯一实现）
# ============================================================================
def reconcile_accounts(db: Session, user_id: int) -> list[dict]:
    """某个账号的余额对账明细：应有余额 = 期初基准 + 全部资金流水，与实际余额对比。

    这是**对账口径的唯一实现** —— 总览页（dashboard）与启动自检都调它，
    避免两处各写一遍导致口径漂移。返回按 |差异| 降序。
    """
    out = []
    for a in db.query(Account).filter(Account.user_id == user_id).all():
        total_flow = round(sum(float(f["amount"]) for f in collect_account_flows(db, a.id, user_id)), 2)
        expected = round(float(a.initial_balance or 0) + total_flow, 2)
        actual = round(float(a.balance or 0), 2)
        out.append({
            "id": a.id, "name": a.name,
            "balance": actual, "expected": expected, "diff": round(actual - expected, 2),
        })
    out.sort(key=lambda x: abs(x["diff"]), reverse=True)
    return out


# 判定「平不平」的容差：SQLite 存 NUMERIC 会带回浮点误差，0.5 分以内视为平
RECONCILE_EPS = 0.005


def reconcile_summary(db: Session, user_ids=None) -> dict:
    """全账号对账摘要（启动自检与 /api/health 用）。

    刻意**只返回摘要不返回明细** —— /api/health 被 Docker HEALTHCHECK 每 30 秒打一次，
    所以调用方必须走缓存（见 `app/health.py`），不能每次实时全量计算。
    """
    from .models import User

    q = db.query(User)
    if user_ids:
        q = q.filter(User.id.in_(list(user_ids)))
    users = q.all()

    accounts = unbalanced = 0
    worst = None
    for u in users:
        for r in reconcile_accounts(db, u.id):
            accounts += 1
            if abs(r["diff"]) > RECONCILE_EPS:
                unbalanced += 1
                if worst is None or abs(r["diff"]) > abs(worst["diff"]):
                    worst = {"user": u.username, "account": r["name"], "diff": r["diff"]}
    return {
        "users": len(users),
        "accounts": accounts,
        "unbalanced": unbalanced,
        "balanced": unbalanced == 0,
        "worst": worst,
    }


# ============================================================================
# 删除归档（回收站）
# ============================================================================
# 从这些字段里挑一个作为「人能看懂的一行摘要」
_LABEL_FIELDS = ("name", "product_name", "counterparty", "label", "title",
                 "company", "note", "type")


def archive_deleted(db: Session, obj, context: dict | None = None):
    """删除前归档一条记录（**只写不读**）。

    调用方负责 commit —— 归档与删除必须在同一个事务里，否则可能出现
    「归档了但没删成」或「删了但没归档」。

    刻意不做成软删除：软删除要让 `collect_account_flows` 的 9 个来源全部记得
    过滤已删记录，漏一处就静默对账失衡。这里放在独立表，余额逻辑一行不改。

    context 用于补充说明（父记录是谁、回滚了哪个账户多少钱），便于日后人工还原。
    """
    from .models import DeletedRecord

    if obj is None or getattr(obj, "id", None) is None:
        return None

    payload = {}
    for col in obj.__table__.columns:
        payload[col.name] = jsonable(getattr(obj, col.name, None))

    label = ""
    for field in _LABEL_FIELDS:
        v = payload.get(field)
        if v:
            label = str(v)
            break
    if not label:
        label = "%s #%s" % (obj.__table__.name, payload.get("id"))

    rec = DeletedRecord(
        user_id=payload.get("user_id") or 1,
        module=obj.__table__.name,
        record_id=obj.id,
        label=label[:200],
        payload=json.dumps(payload, ensure_ascii=False),
        context=json.dumps(context, ensure_ascii=False) if context else None,
    )
    db.add(rec)
    return rec

