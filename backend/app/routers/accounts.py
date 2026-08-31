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
    Transaction,
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
from ..utils import coerce_money, collect_account_flows

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
    account = _get_owned(db, account_id, user.id)
    db.delete(account)
    db.commit()
    return {"ok": True}


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
    db.delete(txn)
    db.commit()
    return {"ok": True}
