from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import InsurancePolicy, PolicyPayment, User
from ..schemas import PolicyCreate, PolicyOut, PolicyUpdate
from ..utils import apply_account_delta, archive_deleted, coerce_money, days_until

router = APIRouter(
    prefix="/api/insurance",
    tags=["保单管理"],
    dependencies=[Depends(get_current_user)],
)


def _add_months(d: date, months: int) -> date:
    """日期加 N 个月（自动处理月末与闰年）"""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    days_in_month = [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28,
                     31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day = min(d.day, days_in_month[m - 1])
    return date(y, m, day)


def _to_out(p: InsurancePolicy) -> PolicyOut:
    out = PolicyOut.model_validate(p)
    out.days_to_due = days_until(p.next_due_date)
    return out


def _get_owned(db: Session, policy_id: int, user_id: int) -> InsurancePolicy:
    policy = db.query(InsurancePolicy).filter(
        InsurancePolicy.id == policy_id, InsurancePolicy.user_id == user_id
    ).first()
    if policy is None:
        raise HTTPException(status_code=404, detail="保单不存在")
    return policy


@router.get("", response_model=list[PolicyOut])
def list_policies(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    policies = db.query(InsurancePolicy).filter(InsurancePolicy.user_id == user.id)\
        .order_by(InsurancePolicy.next_due_date.asc()).all()
    return [_to_out(p) for p in policies]


@router.post("", response_model=PolicyOut)
def create_policy(body: PolicyCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    data = coerce_money(body.model_dump())
    policy = InsurancePolicy(**data, user_id=user.id)
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return _to_out(policy)


@router.put("/{policy_id}", response_model=PolicyOut)
def update_policy(policy_id: int, body: PolicyUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    policy = _get_owned(db, policy_id, user.id)
    data = coerce_money(body.model_dump(exclude_unset=True))
    for k, v in data.items():
        setattr(policy, k, v)
    db.commit()
    db.refresh(policy)
    return _to_out(policy)


@router.delete("/{policy_id}")
def delete_policy(policy_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    policy = _get_owned(db, policy_id, user.id)
    # 删除保单 = 撤销该保单及其全部缴费影响：先按缴费账户逐笔退回保费，再删除缴费记录与保单。
    # 若不退回，账户余额已被扣减而缴费流水消失，余额对账（期初+流水=应有余额）会永久失衡。
    payments = db.query(PolicyPayment).filter(
        PolicyPayment.policy_id == policy.id, PolicyPayment.user_id == user.id
    ).all()
    refund = 0.0
    for p in payments:
        # 逐笔按其「缴费账户快照」退回：中途换过缴费账户时，各笔要退回各自当初出账的账户，
        # 否则新旧账户对账会同时失衡（退款跑到新账户、旧账户却已扣除）。
        target = p.account_id or policy.account_id
        if target:
            apply_account_delta(db, target, float(p.amount))
            refund += float(p.amount)
        archive_deleted(db, p)  # 删除前归档，供事后找回（只写不读）
        db.delete(p)
    archive_deleted(db, policy, {
        "refunded_premium": round(refund, 2),
        "payments_archived": len(payments),
        "note": "已按各笔缴费账户快照退回保费，账户余额已恢复",
    })
    db.delete(policy)
    db.commit()
    msg = f"已删除保单，并退回保费 {refund:.2f} 元（余额已恢复）" if refund else "已删除保单"
    return {"ok": True, "message": msg}


@router.post("/{policy_id}/pay", response_model=PolicyOut)
def pay_policy(policy_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """缴费闭环：从缴费账户扣减保费，生成缴费记录，并自动推进下次缴费日"""
    policy = _get_owned(db, policy_id, user.id)
    if not policy.account_id:
        raise HTTPException(status_code=400, detail="请先为该保单设置缴费账户")
    if not policy.premium:
        raise HTTPException(status_code=400, detail="保费为 0，无需缴费")
    today = date.today()
    apply_account_delta(db, policy.account_id, -float(policy.premium))
    db.add(PolicyPayment(
        user_id=user.id, policy_id=policy.id, account_id=policy.account_id,
        amount=float(policy.premium), date=today, note="保单缴费",
    ))
    policy.last_paid_date = today
    if policy.pay_method == "趸交":
        policy.next_due_date = None
    else:
        step = {"月缴": 1, "季缴": 3, "半年缴": 6, "年缴": 12}.get(policy.pay_method, 12)
        base = policy.next_due_date or today
        policy.next_due_date = _add_months(base, step)
    db.commit()
    db.refresh(policy)
    return _to_out(policy)
