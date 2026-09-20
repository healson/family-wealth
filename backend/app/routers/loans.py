from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Loan, LoanPayment, User
from ..schemas import LoanCreate, LoanOut, LoanPaymentCreate, LoanPaymentOut, LoanUpdate
from ..utils import apply_account_delta, archive_deleted

router = APIRouter(
    prefix="/api/loans",
    tags=["借款管理"],
    dependencies=[Depends(get_current_user)],
)

# 结清判定容差（与前端 remaining 展示保持同一口径）
_EPS = 0.001


def sync_loan_status(db, loan: Loan) -> str:
    """结清状态唯一派生：本金 − 已收/已还 ≤ 0 即「已结清」。

    状态不再由外部写入，也不再与金额各算一套 —— 此前「改金额后状态不重算」会让
    借款页封面（按 status 过滤）与总览（按 remaining 判定）两个口径互相矛盾。
    """
    paid = float(
        db.query(func.coalesce(func.sum(LoanPayment.amount), 0))
        .filter(LoanPayment.loan_id == loan.id)
        .scalar()
        or 0
    )
    loan.status = "已结清" if paid >= float(loan.amount) - _EPS else "未结清"
    return loan.status


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
    # 必须逐条 model_validate，不能直接 `out.payments = loan.payments`：
    # 赋值不触发校验，字段里会留下原始 ORM 对象，序列化时 `Numeric` 的 Decimal
    # 绕过 float 声明 → 接口返回 `"amount": "50.00"`（字符串）并伴随
    # Pydantic serializer warning。逐条校验后与 `amount`/`paid_amount` 同为数字。
    out.payments = [LoanPaymentOut.model_validate(p) for p in loan.payments]
    return out


def _get_owned(db: Session, loan_id: int, user_id: int) -> Loan:
    loan = db.query(Loan).filter(Loan.id == loan_id, Loan.user_id == user_id).first()
    if loan is None:
        raise HTTPException(status_code=404, detail="借款记录不存在")
    return loan


@router.get("", response_model=list[LoanOut])
def list_loans(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """借款列表：**未结清在前**，同组内按借款日期、录入顺序倒序。

    不能用 `Loan.status.asc()` —— 那是字符串排序，中文「已结清」的「已」（U+5DF2）
    编码小于「未结清」的「未」（U+672A），已结清会被顶到列表最前，未结清的活账
    反而压在下面。这里用显式 case 把「已结清」记为 1、其余（含历史遗留状态值）
    记为 0，语义清晰且不受字符集编码影响。
    """
    loans = db.query(Loan).filter(Loan.user_id == user.id)\
        .order_by(
            case((Loan.status == "已结清", 1), else_=0).asc(),
            Loan.date.desc(),
            Loan.id.desc(),
        ).all()
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
    sync_loan_status(db, loan)  # 新建必定未结清，走同一派生入口
    db.commit()
    db.refresh(loan)
    return _to_out(loan, db)


@router.put("/{loan_id}", response_model=LoanOut)
def update_loan(loan_id: int, body: LoanUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """编辑借款。

    注意：**类型不可修改**（`LoanUpdate` 无 `type` 字段），改类型会得到 422 而不是「静默无效」。
    结清状态在应用新金额后由 `sync_loan_status` 重算，保证与 `remaining` 始终一致。
    """
    loan = _get_owned(db, loan_id, user.id)
    data = body.model_dump(exclude_unset=True)
    if "amount" in data and data["amount"] is not None and float(data["amount"]) <= 0:
        raise HTTPException(status_code=400, detail="金额必须大于 0")
    # 先回滚旧影响，再应用新影响
    _apply_loan_balance(db, loan, -1)
    for k, v in data.items():
        setattr(loan, k, v)
    db.flush()
    _apply_loan_balance(db, loan, 1)
    sync_loan_status(db, loan)  # 改金额后重算结清状态（此前会残留旧状态）
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
    archive_deleted(db, loan, {
        "principal": float(loan.amount or 0),
        "collected": round(sum(float(p.amount) for p in loan.payments), 2),
        "payments_archived": len(loan.payments),
        "note": "还款/收款流水与本金对账户的影响已全部回滚",
    })
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
    db.flush()
    sync_loan_status(db, loan)  # 全部还清自动结清（唯一派生入口）
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
    archive_deleted(db, payment)  # 删除前归档，供事后找回（只写不读）
    db.delete(payment)
    db.flush()  # 先落盘删除，派生状态才不会把已删这笔算进去
    sync_loan_status(db, loan)
    db.commit()
    db.refresh(loan)
    return _to_out(loan, db)
