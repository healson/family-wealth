from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import DailyPnl, InvestmentAccount, InvestmentFlow, User
from ..schemas import (
    FinancialCreate,
    FinancialOut,
    FinancialUpdate,
    InvestmentFlowCreate,
    InvestmentFlowOut,
    PnlCreate,
    PnlOut,
)
from ..utils import apply_account_delta, coerce_money

router = APIRouter(
    prefix="/api/financial",
    tags=["投资账户"],
    dependencies=[Depends(get_current_user)],
)


def _get_owned(db: Session, account_id: int, user_id: int) -> InvestmentAccount:
    account = db.query(InvestmentAccount).filter(
        InvestmentAccount.id == account_id, InvestmentAccount.user_id == user_id
    ).first()
    if account is None:
        raise HTTPException(status_code=404, detail="投资账户不存在")
    return account


def _to_out(account: InvestmentAccount, db: Session) -> FinancialOut:
    out = FinancialOut.model_validate(account)
    today = date.today()
    month_start = today.replace(day=1)
    out.today_pnl = float(db.query(func.coalesce(func.sum(DailyPnl.pnl), 0))
                           .filter(DailyPnl.account_id == account.id, DailyPnl.date == today).scalar() or 0)
    out.month_pnl = float(db.query(func.coalesce(func.sum(DailyPnl.pnl), 0))
                          .filter(DailyPnl.account_id == account.id, DailyPnl.date >= month_start).scalar() or 0)
    return out


@router.get("", response_model=list[FinancialOut])
def list_financial(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    accounts = db.query(InvestmentAccount).filter(InvestmentAccount.user_id == user.id)\
        .order_by(InvestmentAccount.created_at.asc()).all()
    return [_to_out(a, db) for a in accounts]


@router.post("", response_model=FinancialOut)
def create_financial(body: FinancialCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    data = coerce_money(body.model_dump())
    account = InvestmentAccount(**data, user_id=user.id)
    db.add(account)
    db.commit()
    db.refresh(account)
    return _to_out(account, db)


@router.put("/{account_id}", response_model=FinancialOut)
def update_financial(account_id: int, body: FinancialUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    account = _get_owned(db, account_id, user.id)
    data = coerce_money(body.model_dump(exclude_unset=True))
    for k, v in data.items():
        setattr(account, k, v)
    db.commit()
    db.refresh(account)
    return _to_out(account, db)


@router.delete("/{account_id}")
def delete_financial(account_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    account = _get_owned(db, account_id, user.id)
    db.delete(account)
    db.commit()
    return {"ok": True}


# ---------- 转入/转出资金流水（强关联现金账户） ----------
@router.get("/{account_id}/flows", response_model=list[InvestmentFlowOut])
def list_flows(account_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    account = _get_owned(db, account_id, user.id)
    return db.query(InvestmentFlow).filter(
        InvestmentFlow.investment_account_id == account.id, InvestmentFlow.user_id == user.id
    ).order_by(InvestmentFlow.date.desc(), InvestmentFlow.id.desc()).all()


@router.post("/{account_id}/flows", response_model=InvestmentFlowOut)
def create_flow(account_id: int, body: InvestmentFlowCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    account = _get_owned(db, account_id, user.id)
    if body.type not in ("转入", "转出"):
        raise HTTPException(status_code=400, detail="类型必须为 转入 或 转出")
    if float(body.amount) <= 0:
        raise HTTPException(status_code=400, detail="金额必须大于 0")
    if not account.cash_account_id:
        raise HTTPException(status_code=400, detail="请先为该投资账户指定关联现金账户（资金来源）")
    flow = InvestmentFlow(
        investment_account_id=account.id, user_id=user.id,
        type=body.type, amount=float(body.amount), date=body.date, note=body.note,
    )
    db.add(flow)
    db.flush()
    if body.type == "转入":  # 现金 → 投资
        apply_account_delta(db, account.cash_account_id, -float(body.amount))
        account.balance = float(account.balance or 0) + float(body.amount)
    else:  # 投资 → 现金
        apply_account_delta(db, account.cash_account_id, float(body.amount))
        account.balance = float(account.balance or 0) - float(body.amount)
    db.commit()
    db.refresh(flow)
    return flow


@router.delete("/{account_id}/flows/{flow_id}")
def delete_flow(account_id: int, flow_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    account = _get_owned(db, account_id, user.id)
    flow = db.query(InvestmentFlow).filter(
        InvestmentFlow.id == flow_id,
        InvestmentFlow.investment_account_id == account.id,
        InvestmentFlow.user_id == user.id,
    ).first()
    if flow is None:
        raise HTTPException(status_code=404, detail="资金流水不存在")
    # 反向回滚：现金账户与投资账户余额
    if flow.type == "转入":
        apply_account_delta(db, account.cash_account_id, float(flow.amount))
        account.balance = float(account.balance or 0) - float(flow.amount)
    else:
        apply_account_delta(db, account.cash_account_id, -float(flow.amount))
        account.balance = float(account.balance or 0) + float(flow.amount)
    db.delete(flow)
    db.commit()
    return {"ok": True}


# ---------- 日盈亏记录 ----------
@router.get("/{account_id}/pnl", response_model=list[PnlOut])
def list_pnl(
    account_id: int,
    month: str | None = Query(None, description="YYYY-MM"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    account = _get_owned(db, account_id, user.id)
    query = db.query(DailyPnl).filter(DailyPnl.account_id == account.id, DailyPnl.user_id == user.id)
    if month:
        query = query.filter(func.strftime("%Y-%m", DailyPnl.date) == month)
    return query.order_by(DailyPnl.date.desc()).all()


@router.get("/records")
def financial_records(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """统一盈亏记录：全部投资账户日盈亏（按时间倒序）"""
    records = []
    pnls = db.query(DailyPnl, InvestmentAccount).join(
        InvestmentAccount, DailyPnl.account_id == InvestmentAccount.id
    ).filter(DailyPnl.user_id == user.id).all()
    for p, a in pnls:
        val = float(p.pnl)
        records.append({
            "id": f"p{p.id}", "date": p.date.isoformat(),
            "amount": abs(val), "type": "盈利" if val >= 0 else "亏损",
            "label": a.name if a else "投资账户",
            "note": p.note, "sub": f"{'盈利' if val >= 0 else '亏损'} {abs(val):.2f}",
        })
    records.sort(key=lambda r: r["date"], reverse=True)
    return records


@router.post("/{account_id}/pnl", response_model=PnlOut)
def create_pnl(account_id: int, body: PnlCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    account = _get_owned(db, account_id, user.id)
    data = coerce_money(body.model_dump())
    record = DailyPnl(account_id=account.id, user_id=user.id, **data)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.delete("/{account_id}/pnl/{pnl_id}")
def delete_pnl(account_id: int, pnl_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    record = db.query(DailyPnl).filter(
        DailyPnl.id == pnl_id,
        DailyPnl.account_id == account_id,
        DailyPnl.user_id == user.id,
    ).first()
    if record is None:
        raise HTTPException(status_code=404, detail="盈亏记录不存在")
    db.delete(record)
    db.commit()
    return {"ok": True}
