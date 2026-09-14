"""交易模板 + 定时交易"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import ScheduledTransaction, Transaction, TransactionTemplate, User
from ..schedulers import calc_first_next, calc_next, frequency_label, run_due
from ..schemas import (
    ScheduledCreate,
    ScheduledOut,
    ScheduledUpdate,
    TemplateCreate,
    TemplateOut,
)
from ..utils import apply_txn_balance, coerce_money

router = APIRouter(
    prefix="/api",
    tags=["交易模板与定时交易"],
    dependencies=[Depends(get_current_user)],
)


def _template_out(t: TransactionTemplate) -> TemplateOut:
    return TemplateOut.model_validate(t)


def _scheduled_out(s: ScheduledTransaction) -> ScheduledOut:
    out = ScheduledOut.model_validate(s)
    out.frequency_label = frequency_label(s)
    out.next_label = f"{s.next_run_date:%Y-%m-%d}"
    return out


# ---------- 交易模板 ----------
@router.get("/templates", response_model=list[TemplateOut])
def list_templates(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(TransactionTemplate).filter(TransactionTemplate.user_id == user.id)\
        .order_by(TransactionTemplate.created_at.desc()).all()


@router.post("/templates", response_model=TemplateOut)
def create_template(body: TemplateCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="模板名称不能为空")
    if float(body.amount) <= 0:
        raise HTTPException(status_code=400, detail="金额必须大于 0")
    data = coerce_money(body.model_dump())
    t = TransactionTemplate(**data, user_id=user.id)
    db.add(t)
    db.commit()
    db.refresh(t)
    return _template_out(t)


@router.put("/templates/{template_id}", response_model=TemplateOut)
def update_template(template_id: int, body: TemplateCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    t = db.query(TransactionTemplate).filter(
        TransactionTemplate.id == template_id, TransactionTemplate.user_id == user.id
    ).first()
    if t is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    data = coerce_money(body.model_dump())
    for k, v in data.items():
        setattr(t, k, v)
    db.commit()
    db.refresh(t)
    return _template_out(t)


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    t = db.query(TransactionTemplate).filter(
        TransactionTemplate.id == template_id, TransactionTemplate.user_id == user.id
    ).first()
    if t is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    db.delete(t)
    db.commit()
    return {"ok": True}


# ---------- 定时交易 ----------
@router.get("/scheduled", response_model=list[ScheduledOut])
def list_scheduled(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    items = db.query(ScheduledTransaction).filter(ScheduledTransaction.user_id == user.id)\
        .order_by(ScheduledTransaction.active.desc(), ScheduledTransaction.next_run_date.asc()).all()
    return [_scheduled_out(s) for s in items]


@router.post("/scheduled", response_model=ScheduledOut)
def create_scheduled(body: ScheduledCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if body.frequency not in ("monthly", "weekly", "yearly"):
        raise HTTPException(status_code=400, detail="频率必须为 monthly/weekly/yearly")
    if float(body.amount) <= 0:
        raise HTTPException(status_code=400, detail="金额必须大于 0")
    if body.frequency == "weekly" and not (0 <= body.day <= 6):
        raise HTTPException(status_code=400, detail="每周模式需选择周一~周日")
    data = coerce_money(body.model_dump())
    item = ScheduledTransaction(**data, user_id=user.id)
    item.next_run_date = calc_first_next(item)
    if item.end_date and item.next_run_date > item.end_date:
        item.active = 0
    db.add(item)
    db.commit()
    db.refresh(item)
    return _scheduled_out(item)


@router.put("/scheduled/{item_id}", response_model=ScheduledOut)
def update_scheduled(item_id: int, body: ScheduledUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.query(ScheduledTransaction).filter(
        ScheduledTransaction.id == item_id, ScheduledTransaction.user_id == user.id
    ).first()
    if item is None:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(item, k, v)
    # 重算下次执行日（从 start_date 或 last_run_date 之后）
    if any(k in data for k in ("frequency", "day", "yearly_month", "start_date", "end_date")):
        base = item.last_run_date or item.start_date
        item.next_run_date = calc_next(item, base) if item.last_run_date else calc_first_next(item)
        if item.end_date and item.next_run_date > item.end_date:
            item.active = 0
    db.commit()
    db.refresh(item)
    return _scheduled_out(item)


@router.delete("/scheduled/{item_id}")
def delete_scheduled(item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.query(ScheduledTransaction).filter(
        ScheduledTransaction.id == item_id, ScheduledTransaction.user_id == user.id
    ).first()
    if item is None:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.post("/scheduled/{item_id}/run-now")
def run_now(item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """立即执行一次：按今天生成记录并顺延下次执行日"""
    item = db.query(ScheduledTransaction).filter(
        ScheduledTransaction.id == item_id, ScheduledTransaction.user_id == user.id
    ).first()
    if item is None:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    today = date.today()
    note = f"⏰{item.name}"
    if item.note:
        note += f"·{item.note}"
    txn = Transaction(
        user_id=user.id, type=item.type, amount=item.amount,
        category_id=item.category_id, account_id=item.account_id,
        date=today, note=note[:200],
    )
    db.add(txn)
    db.flush()
    apply_txn_balance(db, txn, 1)  # 与调度器 run_due 保持一致：立即执行同样联动账户余额
    item.last_run_date = today
    item.next_run_date = calc_next(item, today)
    if item.end_date and item.next_run_date > item.end_date:
        item.active = 0
    db.commit()
    return {"ok": True, "message": "已生成今日记录并顺延下次执行日"}


@router.post("/scheduled/check-due")
def check_due(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """手动触发一次到期检查（返回本次生成的记录数）"""
    count = run_due(db)
    return {"ok": True, "generated": count}
