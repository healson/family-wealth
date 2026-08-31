from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Category, Transaction, User
from ..schemas import (
    CategoryCreate,
    CategoryOut,
    TransactionCreate,
    TransactionOut,
    TransactionUpdate,
)
from ..utils import apply_txn_balance, coerce_money

router = APIRouter(
    prefix="/api/transactions",
    tags=["日常收支"],
    dependencies=[Depends(get_current_user)],
)


# ---------- 分类 ----------
# 默认收支分类：某类型没有分类时自动补齐（新账号 / 空库 / 分类曾被清空的账号）
_DEFAULT_CATEGORIES = {
    "收入": ["工资收入", "理财收益", "奖金", "其他收入"],
    "支出": ["餐饮", "交通", "居住", "购物", "医疗", "教育", "娱乐", "人情往来", "其他支出"],
}


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    for ctype, names in _DEFAULT_CATEGORIES.items():
        exists = db.query(Category).filter(Category.user_id == user.id, Category.type == ctype).first()
        if exists is None:
            for name in names:
                db.add(Category(name=name, type=ctype, user_id=user.id))
            db.commit()
    return db.query(Category).filter(Category.user_id == user.id)\
        .order_by(Category.type.desc(), Category.id.asc()).all()


@router.post("/categories", response_model=CategoryOut)
def create_category(body: CategoryCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    category = Category(**body.model_dump(), user_id=user.id)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@router.delete("/categories/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    category = db.query(Category).filter(Category.id == category_id, Category.user_id == user.id).first()
    if category is None:
        raise HTTPException(status_code=404, detail="分类不存在")
    # 引用该分类的记录置为未分类（交易/模板/定时任务）
    db.query(Transaction).filter(Transaction.category_id == category.id).update({Transaction.category_id: None})
    from ..models import ScheduledTransaction, TransactionTemplate

    db.query(TransactionTemplate).filter(TransactionTemplate.category_id == category.id).update({TransactionTemplate.category_id: None})
    db.query(ScheduledTransaction).filter(ScheduledTransaction.category_id == category.id).update({ScheduledTransaction.category_id: None})
    db.delete(category)
    db.commit()
    return {"ok": True, "message": f"分类「{category.name}」已删除，相关记录已置为未分类"}


# ---------- 收支记录 ----------
@router.get("", response_model=list[TransactionOut])
def list_transactions(
    type: str | None = None,
    year: int | None = None,
    month: int | None = None,
    category_id: int | None = None,
    limit: int = Query(200, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(Transaction).filter(Transaction.user_id == user.id)
    if type:
        query = query.filter(Transaction.type == type)
    if year:
        query = query.filter(func.strftime("%Y", Transaction.date) == f"{year:04d}")
    if month:
        query = query.filter(func.strftime("%m", Transaction.date) == f"{month:02d}")
    if category_id:
        query = query.filter(Transaction.category_id == category_id)
    return query.order_by(Transaction.date.desc(), Transaction.id.desc()).limit(limit).all()


@router.post("", response_model=TransactionOut)
def create_transaction(body: TransactionCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    data = coerce_money(body.model_dump())
    if not data.get("account_id"):
        raise HTTPException(status_code=400, detail="强关联模式下请选择账户（收入/支出将自动增减账户余额）")
    txn = Transaction(**data, user_id=user.id)
    db.add(txn)
    db.flush()
    apply_txn_balance(db, txn, 1)  # 收入+ / 支出−，同步账户余额
    db.commit()
    db.refresh(txn)
    return txn


@router.put("/{txn_id}", response_model=TransactionOut)
def update_transaction(txn_id: int, body: TransactionUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    txn = db.query(Transaction).filter(Transaction.id == txn_id, Transaction.user_id == user.id).first()
    if txn is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    data = coerce_money(body.model_dump(exclude_unset=True))
    if data.get("account_id") is None and "account_id" in data:
        raise HTTPException(status_code=400, detail="强关联模式下请选择账户")
    # 先回滚旧影响，再应用新影响
    apply_txn_balance(db, txn, -1)
    for k, v in data.items():
        setattr(txn, k, v)
    db.flush()
    apply_txn_balance(db, txn, 1)
    db.commit()
    db.refresh(txn)
    return txn


@router.delete("/{txn_id}")
def delete_transaction(txn_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    txn = db.query(Transaction).filter(Transaction.id == txn_id, Transaction.user_id == user.id).first()
    if txn is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    apply_txn_balance(db, txn, -1)  # 反向恢复余额
    db.delete(txn)
    db.commit()
    return {"ok": True}
