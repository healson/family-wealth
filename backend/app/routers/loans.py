from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Loan, LoanPayment, User
from ..schemas import LoanCreate, LoanOut, LoanPaymentCreate, LoanPaymentOut, LoanUpdate
from ..utils import apply_account_delta

router = APIRouter(
    prefix="/api/loans",
    tags=["借款管理"],
    dependencies=[Depends(get_current_user)],
)


def _apply_loan_balance(db, loan, sign=1):
    """借款本金联动余额：借出=从账户出账（−），借入=入账（+）"""
    if not loan.account_id or not loan.amount:
        return
    delta = -float(loan.amount) if loan.type == "借出" else float(loan.amount)
    apply_account_delta(db, loan.account_id, delta * sign)


def _apply_payment_balance(db, payment, loan, sign=1):
    """收款/还款联动余额：借出收款=入账（+），借入还款=出账（−）"""
    if not payment.account_id or not payment.amount:
        return
    delta = float(payment.amount) if loan.type == "借出" else -float(payment.amount)
    apply_account_delta(db, payment.account_id, delta * sign)


def _to_out(loan: Loan, db: Session) -> LoanOut:
    out = LoanOut.model_validate(loan)
    paid = sum(float(p.amount) for p in loan.payments)
    out.paid_amount = round(paid, 2)
    out.remaining = round(float(loan.amount) - paid, 2)
    out.overdue = out.remaining > 0 and loan.due_date is not None and loan.due_date < date.today()
    out.payments = loan.payments
    return out


def _get_owned(db: Session, loan_id: int, user_id: int) -> Loan:
    loan = db.query(Loan).filter(Loan.id == loan_id, Loan.user_id == user_id).first()
    if loan is None:
        raise HTTPException(status_code=404, detail="借款记录不存在")
    return loan


@router.get("", response_model=list[LoanOut])
def list_loans(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    loans = db.query(Loan).filter(Loan.user_id == user.id)\
        .order_by(Loan.status.asc(), Loan.date.desc(), Loan.id.desc()).all()
    return [_to_out(l, db) for l in loans]


@router.post("", response_model=LoanOut)
def create_loan(body: LoanCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if body.type not in ("借出", "借入"):
        raise HTTPException(status_code=400, detail="类型必须为 借出 或 借入")
    if float(body.amount) <= 0:
        raise HTTPException(status_code=400, detail="金额必须大于 0")
    loan = Loan(**body.model_dump(), user_id=user.id)
    db.add(loan)
    db.flush()
    _apply_loan_balance(db, loan, 1)  # 借出扣账户、借入加账户
    db.commit()
    db.refresh(loan)
    return _to_out(loan, db)


@router.put("/{loan_id}", response_model=LoanOut)
def update_loan(loan_id: int, body: LoanUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    loan = _get_owned(db, loan_id, user.id)
    data = body.model_dump(exclude_unset=True)
    # 先回滚旧影响，再应用新影响
    _apply_loan_balance(db, loan, -1)
    for k, v in data.items():
        setattr(loan, k, v)
    db.flush()
    _apply_loan_balance(db, loan, 1)
    db.commit()
    db.refresh(loan)
    return _to_out(loan, db)


@router.delete("/{loan_id}")
def delete_loan(loan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    loan = _get_owned(db, loan_id, user.id)
    # 先回滚所有还款/收款流水，再回滚本金
    for p in loan.payments:
        _apply_payment_balance(db, p, loan, -1)
    _apply_loan_balance(db, loan, -1)
    db.delete(loan)
    db.commit()
    return {"ok": True}


@router.get("/records")
def loan_records(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """统一流水记录：借款发生 + 还款/收款（按时间倒序）"""
    records = []
    loans = db.query(Loan).filter(Loan.user_id == user.id).all()
    for l in loans:
        records.append({
            "id": f"l{l.id}", "date": l.date.isoformat(),
            "amount": float(l.amount), "type": l.type,
            "label": l.counterparty, "note": l.note, "sub": f"借款金额 {float(l.amount):.2f}",
        })
        for p in l.payments:
            records.append({
                "id": f"p{p.id}", "date": p.date.isoformat(),
                "amount": float(p.amount),
                "type": "收款" if l.type == "借出" else "还款",
                "label": l.counterparty, "note": p.note, "sub": f"原借款 {l.type} {float(l.amount):.2f}",
            })
    records.sort(key=lambda r: r["date"], reverse=True)
    return records


# ---------- 还款/收款流水 ----------
@router.get("/{loan_id}/payments", response_model=list[LoanPaymentOut])
def list_payments(loan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    loan = _get_owned(db, loan_id, user.id)
    return loan.payments


@router.post("/{loan_id}/payments", response_model=LoanOut)
def add_payment(loan_id: int, body: LoanPaymentCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    loan = _get_owned(db, loan_id, user.id)
    if float(body.amount) <= 0:
        raise HTTPException(status_code=400, detail="金额必须大于 0")
    payment = LoanPayment(loan_id=loan.id, user_id=user.id, amount=float(body.amount), date=body.date, account_id=body.account_id, note=body.note)
    db.add(payment)
    db.flush()
    _apply_payment_balance(db, payment, loan, 1)  # 借出收款入账 / 借入还款出账
    # 全部还清自动结清
    paid = sum(float(p.amount) for p in loan.payments) + float(body.amount)
    if paid >= float(loan.amount) - 0.001:
        loan.status = "已结清"
    else:
        loan.status = "未结清"
    db.commit()
    db.refresh(loan)
    return _to_out(loan, db)


@router.delete("/{loan_id}/payments/{payment_id}", response_model=LoanOut)
def delete_payment(loan_id: int, payment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    loan = _get_owned(db, loan_id, user.id)
    payment = db.query(LoanPayment).filter(
        LoanPayment.id == payment_id, LoanPayment.loan_id == loan.id, LoanPayment.user_id == user.id
    ).first()
    if payment is None:
        raise HTTPException(status_code=404, detail="还款记录不存在")
    _apply_payment_balance(db, payment, loan, -1)  # 反向回滚余额
    db.delete(payment)
    # 删除后按剩余金额回置状态
    paid = sum(float(p.amount) for p in loan.payments if p.id != payment_id)
    loan.status = "已结清" if paid >= float(loan.amount) - 0.001 else "未结清"
    db.commit()
    db.refresh(loan)
    return _to_out(loan, db)
