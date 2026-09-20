from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import InsurancePolicy, Loan, ReminderDismissal, ReminderRule, User
from ..schemas import (
    ReminderItemOut,
    ReminderRuleCreate,
    ReminderRuleOut,
    ReminderRuleUpdate,
)
from ..utils import archive_deleted, days_until

router = APIRouter(
    prefix="/api/reminders",
    tags=["提醒"],
    dependencies=[Depends(get_current_user)],
)

DEFAULT_RULES = [
    {"label": "提前1个月", "lead_days": 30},
    {"label": "提前1周", "lead_days": 7},
    {"label": "提前3天", "lead_days": 3},
    {"label": "提前2天", "lead_days": 2},
    {"label": "提前1天", "lead_days": 1},
]


def ensure_default_rules(db: Session, user_id: int):
    """新用户首次访问时，初始化 5 条默认续期提醒规则"""
    count = db.query(ReminderRule).filter(ReminderRule.user_id == user_id).count()
    if count == 0:
        for r in DEFAULT_RULES:
            db.add(ReminderRule(user_id=user_id, label=r["label"], lead_days=r["lead_days"], scope="all", enabled=1))
        db.commit()


def dedupe_rules(db: Session, user_id: int):
    """清理重复的提醒规则：同 (label+lead_days+scope) 只保留最早一条，其余删除"""
    rows = db.query(ReminderRule).filter(ReminderRule.user_id == user_id).order_by(ReminderRule.id.asc()).all()
    seen = {}
    to_delete = []
    for r in rows:
        key = (r.label.strip(), r.lead_days, r.scope)
        if key in seen:
            to_delete.append(r)
        else:
            seen[key] = r
    for r in to_delete:
        db.delete(r)
    if to_delete:
        db.commit()


@router.get("/rules", response_model=list[ReminderRuleOut])
def list_rules(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ensure_default_rules(db, user.id)
    dedupe_rules(db, user.id)
    return db.query(ReminderRule).filter(ReminderRule.user_id == user.id).order_by(ReminderRule.lead_days.desc()).all()


@router.post("/rules", response_model=ReminderRuleOut)
def create_rule(body: ReminderRuleCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if body.lead_days < 0:
        raise HTTPException(status_code=400, detail="提前天数不能为负")
    label = body.label.strip() or f"提前{body.lead_days}天"
    dup = db.query(ReminderRule).filter(
        ReminderRule.user_id == user.id,
        ReminderRule.label == label,
        ReminderRule.lead_days == body.lead_days,
        ReminderRule.scope == body.scope,
    ).first()
    if dup:
        raise HTTPException(status_code=400, detail=f"已存在相同规则「{label}（提前{body.lead_days}天）」，请勿重复添加")
    rule = ReminderRule(
        user_id=user.id,
        label=label,
        lead_days=body.lead_days,
        scope=body.scope,
        enabled=body.enabled,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/rules/{rule_id}", response_model=ReminderRuleOut)
def update_rule(rule_id: int, body: ReminderRuleUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rule = db.query(ReminderRule).filter(ReminderRule.id == rule_id, ReminderRule.user_id == user.id).first()
    if rule is None:
        raise HTTPException(status_code=404, detail="提醒规则不存在")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rule = db.query(ReminderRule).filter(ReminderRule.id == rule_id, ReminderRule.user_id == user.id).first()
    if rule is None:
        raise HTTPException(status_code=404, detail="提醒规则不存在")
    archive_deleted(db, rule)  # 删除前归档，供事后找回（只写不读）
    db.delete(rule)
    db.commit()
    return {"ok": True}


@router.get("/pending", response_model=list[ReminderItemOut])
def pending(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ensure_default_rules(db, user.id)
    dedupe_rules(db, user.id)
    rules = db.query(ReminderRule).filter(ReminderRule.user_id == user.id, ReminderRule.enabled == 1).all()
    if not rules:
        return []

    # 收集待提醒的到期项（module, record_id, title, due_date, due_type）
    due_items = []
    policies = db.query(InsurancePolicy).filter(InsurancePolicy.user_id == user.id).all()
    for p in policies:
        if p.next_due_date:
            due_items.append(("insurance", p.id, f"{p.company} {p.product_name}", p.next_due_date, "续保/缴费"))
        if p.end_date:
            due_items.append(("insurance", p.id, f"{p.company} {p.product_name}", p.end_date, "到期"))
    loans = db.query(Loan).filter(Loan.user_id == user.id, Loan.status != "已结清").all()
    for l in loans:
        if l.due_date:
            due_items.append(("loan", l.id, f"{l.type}·{l.counterparty}", l.due_date, "还款"))

    # 已忽略的集合
    dismissals = db.query(ReminderDismissal).filter(ReminderDismissal.user_id == user.id).all()
    dismissed = {(d.rule_id, d.module, d.record_id, d.due_date) for d in dismissals}

    result = []
    today = date.today()
    for module, record_id, title, due, due_type in due_items:
        due_str = due.strftime("%Y-%m-%d")
        left = (due - today).days
        if left < 0:
            continue  # 已过期不提醒
        for rule in rules:
            if rule.scope not in ("all", module):
                continue
            if left <= rule.lead_days and (rule.id, module, record_id, due_str) not in dismissed:
                result.append(ReminderItemOut(
                    rule_id=rule.id,
                    rule_label=rule.label,
                    module=module,
                    record_id=record_id,
                    title=title,
                    due_date=due_str,
                    due_type=due_type,
                    days_left=left,
                ))
    # 按剩余天数升序，最紧急的排前面
    result.sort(key=lambda x: (x.days_left, x.module, x.record_id))
    return result


@router.post("/dismiss")
def dismiss(body: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """标记某条（规则+记录+到期日）提醒为已读，不再弹出"""
    rule_id = body.get("rule_id")
    module = body.get("module")
    record_id = body.get("record_id")
    due_date = body.get("due_date")
    if not all([rule_id, module, record_id is not None, due_date]):
        raise HTTPException(status_code=400, detail="参数错误")
    exists = db.query(ReminderDismissal).filter(
        ReminderDismissal.user_id == user.id,
        ReminderDismissal.rule_id == rule_id,
        ReminderDismissal.module == module,
        ReminderDismissal.record_id == record_id,
        ReminderDismissal.due_date == due_date,
    ).first()
    if not exists:
        db.add(ReminderDismissal(
            user_id=user.id, rule_id=rule_id, module=module, record_id=record_id, due_date=due_date
        ))
        db.commit()
    return {"ok": True}
