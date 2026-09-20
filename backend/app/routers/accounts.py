from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import (
    Account,
    AccountTransaction,
    Asset,
    InsurancePolicy,
    InvestmentAccount,
    InvestmentFlow,
    Loan,
    LoanPayment,
    PolicyPayment,
    ScheduledTransaction,
    Transaction,
    TransactionTemplate,
    Transfer,
    User,
)
from ..schemas import (
    AccountCreate,
    AccountOut,
    AccountTransactionCreate,
    AccountTransactionOut,
    AccountUpdate,
)
from ..utils import apply_account_delta, archive_deleted, coerce_money, collect_account_flows

router = APIRouter(
    prefix="/api/accounts",
    tags=["现金账户"],
    dependencies=[Depends(get_current_user)],
)


def _get_owned(db: Session, account_id: int, user_id: int) -> Account:
    account = db.query(Account).filter(Account.id == account_id, Account.user_id == user_id).first()
    if account is None:
        raise HTTPException(status_code=404, detail="账户不存在")
    return account


@router.get("", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Account).filter(Account.user_id == user.id).order_by(Account.created_at.asc()).all()


@router.post("", response_model=AccountOut)
def create_account(body: AccountCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    data = coerce_money(body.model_dump())
    if data.get("initial_balance") is None:
        data["initial_balance"] = float(data.get("balance", 0))  # 默认期初=当前余额（余额为基准）
    account = Account(**data, user_id=user.id)
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.put("/{account_id}", response_model=AccountOut)
def update_account(account_id: int, body: AccountUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    account = _get_owned(db, account_id, user.id)
    data = coerce_money(body.model_dump(exclude_unset=True))
    for k, v in data.items():
        setattr(account, k, v)
    db.commit()
    db.refresh(account)
    return account


@router.delete("/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除现金账户（含连带清理，避免破坏资金守恒与余额对账）。

    1) 转账：把已发生的转账影响从**对方账户**退回/扣回，再删除转账记录
       （否则对方账户余额已变、流水却消失，对账会出现永久性差异）；
    2) 其余模块：解除对该账户的引用（置空），避免留下指向已删账户的悬挂关联。
       收支记录本身保留（历史事实保留在收入/支出统计中），仅解除账户关联。
    """
    account = _get_owned(db, account_id, user.id)

    # 1) 撤销转账对对方账户的影响
    transfers = db.query(Transfer).filter(
        Transfer.user_id == user.id,
        (Transfer.from_account_id == account.id) | (Transfer.to_account_id == account.id),
    ).all()
    for t in transfers:
        amount = float(t.amount)
        if t.from_account_id == account.id and t.to_account_id != account.id:
            apply_account_delta(db, t.to_account_id, -amount)  # 对方当初 + → 扣回
        elif t.to_account_id == account.id and t.from_account_id != account.id:
            apply_account_delta(db, t.from_account_id, amount)  # 对方当初 − → 退回
        archive_deleted(db, t)  # 删除前归档，供事后找回（只写不读）
        db.delete(t)

    # 2) 解除其余模块对账户的引用
    db.query(Transaction).filter(Transaction.account_id == account.id).update({Transaction.account_id: None})
    db.query(Loan).filter(Loan.account_id == account.id).update({Loan.account_id: None})
    db.query(LoanPayment).filter(LoanPayment.account_id == account.id).update({LoanPayment.account_id: None})
    db.query(Asset).filter(Asset.account_id == account.id).update({Asset.account_id: None})
    db.query(InsurancePolicy).filter(InsurancePolicy.account_id == account.id).update({InsurancePolicy.account_id: None})
    # 保单缴费 / 投资流水的「账户快照」也要解引用，避免留下指向已删账户的悬挂归属
    db.query(PolicyPayment).filter(PolicyPayment.account_id == account.id).update({PolicyPayment.account_id: None})
    db.query(InvestmentFlow).filter(InvestmentFlow.cash_account_id == account.id).update({InvestmentFlow.cash_account_id: None})
    db.query(InvestmentAccount).filter(InvestmentAccount.cash_account_id == account.id)\
        .update({InvestmentAccount.cash_account_id: None})
    db.query(TransactionTemplate).filter(TransactionTemplate.account_id == account.id)\
        .update({TransactionTemplate.account_id: None})
    db.query(ScheduledTransaction).filter(ScheduledTransaction.account_id == account.id)\
        .update({ScheduledTransaction.account_id: None})

    archive_deleted(db, account, {
        "account_name": account.name,
        "type": account.type,
        "balance_at_delete": float(account.balance or 0),
        "initial_balance": float(account.initial_balance or 0),
        "revoked_transfers": len(transfers),
        "note": "账户存取流水随账户级联删除；其余模块对该账户的引用已置空（那些记录本身保留）",
    })
    db.delete(account)  # 账户存取流水由 ORM 级联删除
    db.commit()
    return {"ok": True, "message": f"已删除账户「{account.name}」并清理关联（撤销 {len(transfers)} 笔转账对对方账户的影响）"}


def _flow_type(f: dict) -> str:
    """把全链路流水条目映射为语义类型（账户视角：正=资金流入该账户）"""
    kind = f.get("kind")
    if kind == "收支":
        return "收入" if f["amount"] > 0 else "支出"
    if kind == "存取":
        return f.get("title") or "存取"
    if kind == "转账":
        return "转入" if f["amount"] > 0 else "转出"
    if kind == "借款":
        title = f.get("title") or ""
        if title.startswith("借出"):
            return "借出"
        if title.startswith("借入"):
            return "借入"
        if title.startswith("收款"):
            return "收款"
        return "还款"
    if kind == "保单":
        return "保单缴费"
    if kind == "资产":
        return "资产购入"
    if kind == "投资":
        return "投资转入" if f["amount"] < 0 else "投资转出"
    return kind or "其他"


@router.get("/records")
def account_records(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """统一流水记录（全链路）：汇总全部现金账户相关的收支/存取/转账/借贷/保单/资产/投资动作，按时间倒序"""
    records = []
    seq = 0
    for a in db.query(Account).filter(Account.user_id == user.id).all():
        for f in collect_account_flows(db, a.id, user.id):
            seq += 1
            records.append({
                "id": f"k{seq}",
                "date": f["date"],
                "amount": round(abs(float(f["amount"])), 2),  # 金额绝对值，方向由 type 表达
                "type": _flow_type(f),
                "label": a.name,
                "note": f.get("title") or "",
                "sub": f.get("kind") or "",
            })
    records.sort(key=lambda r: r["date"], reverse=True)
    return records


@router.get("/{account_id}/ledger")
def account_ledger(account_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """账户资金流水：汇总与该账户相关的全部强关联动作（收支/存取/转账/借贷/保单/资产/投资）"""
    account = _get_owned(db, account_id, user.id)
    rows = collect_account_flows(db, account.id, user.id)
    rows.sort(key=lambda r: r["date"], reverse=True)
    # 从当前余额回溯计算每笔发生后的余额
    bal = float(account.balance or 0)
    for i, r in enumerate(rows):
        r["balance_after"] = round(bal, 2)
        bal -= r["amount"]
    return rows


# ---------- 账户流水 ----------
@router.get("/{account_id}/transactions", response_model=list[AccountTransactionOut])
def list_account_transactions(account_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    account = _get_owned(db, account_id, user.id)
    return db.query(AccountTransaction).filter(AccountTransaction.account_id == account.id)\
        .order_by(AccountTransaction.date.desc()).all()


@router.post("/{account_id}/transactions", response_model=AccountTransactionOut)
def create_account_transaction(
    account_id: int, body: AccountTransactionCreate, db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    account = _get_owned(db, account_id, user.id)
    data = coerce_money(body.model_dump())
    txn = AccountTransaction(account_id=account.id, user_id=user.id, **data)
    # 同步账户余额：存入增加，取出减少
    delta = float(data["amount"]) if data["type"] == "存入" else -float(data["amount"])
    account.balance = float(account.balance) + delta
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


@router.delete("/{account_id}/transactions/{txn_id}")
def delete_account_transaction(account_id: int, txn_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    txn = db.query(AccountTransaction).filter(
        AccountTransaction.id == txn_id,
        AccountTransaction.account_id == account_id,
        AccountTransaction.user_id == user.id,
    ).first()
    if txn is None:
        raise HTTPException(status_code=404, detail="流水不存在")
    # 回滚余额
    account = _get_owned(db, account_id, user.id)
    delta = -float(txn.amount) if txn.type == "存入" else float(txn.amount)
    account.balance = float(account.balance) + delta
    archive_deleted(db, txn)  # 删除前归档，供事后找回（只写不读）
    db.delete(txn)
    db.commit()
    return {"ok": True}
