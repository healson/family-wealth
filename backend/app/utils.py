from datetime import date, datetime, timedelta

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


def collect_account_flows(db: Session, account_id: int, user_id: int) -> list[dict]:
    """收集某账户相关的全部资金动作（统一口径，供资金流水展示与余额对账使用）。
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
        .filter(InsurancePolicy.account_id == account_id, PolicyPayment.user_id == user_id).all()
    for p in payments:
        rows.append({
            "date": p.date.isoformat(), "kind": "保单",
            "title": f"缴费 · {p.policy.product_name if p.policy else '保单'}",
            "amount": -round(float(p.amount), 2),
            "note": p.note,
            "ref_type": "policy_payment", "ref_id": p.id,
            "ref_parent_id": p.policy_id,
        })
    # 固定资产购入
    for a in db.query(Asset).filter(Asset.account_id == account_id, Asset.user_id == user_id).all():
        d = (a.purchase_date or a.created_at.date()).isoformat()
        rows.append({"date": d, "kind": "资产", "title": f"购入 · {a.name}", "amount": -round(float(a.purchase_price), 2), "note": a.note, "ref_type": "asset", "ref_id": a.id, "ref_parent_id": None})
    # 投资转入/转出（现金账户视角）
    invs = db.query(InvestmentAccount).filter(InvestmentAccount.cash_account_id == account_id, InvestmentAccount.user_id == user_id).all()
    if invs:
        inv_ids = [x.id for x in invs]
        inv_map = {x.id: x.name for x in invs}
        for f in db.query(InvestmentFlow).filter(InvestmentFlow.investment_account_id.in_(inv_ids), InvestmentFlow.user_id == user_id).all():
            rows.append({
                "date": f.date.isoformat(), "kind": "投资",
                "title": f"{f.type} · {inv_map.get(f.investment_account_id, '投资')}",
                "amount": -round(float(f.amount), 2) if f.type == "转入" else round(float(f.amount), 2),
                "note": f.note,
                "ref_type": "investment_flow", "ref_id": f.id,
                "ref_parent_id": f.investment_account_id,
            })
    return rows
