"""数据导出/导入（JSON 全量备份与恢复，按账号隔离）"""
from datetime import date, datetime

import sqlalchemy
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import USER_SCOPED_MODELS, delete_user_data, get_current_user
from ..database import get_db
from ..models import (
    Account,
    AccountTransaction,
    Asset,
    AssetValuation,
    Attachment,
    Category,
    CustomOption,
    DailyPnl,
    InsurancePolicy,
    InvestmentAccount,
    InvestmentFlow,
    Loan,
    LoanPayment,
    PolicyPayment,
    ReminderDismissal,
    ReminderRule,
    ScheduledTransaction,
    Transaction,
    TransactionTemplate,
    Transfer,
    User,
)

router = APIRouter(
    prefix="/api/data",
    tags=["数据导入导出"],
    dependencies=[Depends(get_current_user)],
)

EXPORT_VERSION = 1

# 各表的导出字段与模型映射（依赖顺序：先父表后子表；Account 放最前以便账户外键映射）
_PARENT_MODELS = [Account, CustomOption, Category, Asset, InsurancePolicy, InvestmentAccount, Loan, TransactionTemplate, ScheduledTransaction]
_CHILD_MODELS = [InvestmentFlow, PolicyPayment, AssetValuation, AccountTransaction, DailyPnl, Transfer, Transaction, LoanPayment]


def _serialize(model_obj):
    d = {}
    for col in model_obj.__table__.columns:
        v = getattr(model_obj, col.name)
        if isinstance(v, (date, datetime)):
            v = v.isoformat()
        d[col.name] = v
    return d


def _convert_cols(model, row: dict):
    """将字符串形式的日期/时间列转为对应 Python 类型（导入用）"""
    for col in model.__table__.columns:
        v = row.get(col.name)
        if v is None or not isinstance(v, str):
            continue
        try:
            if isinstance(col.type, sqlalchemy.DateTime):
                row[col.name] = datetime.fromisoformat(v)
            elif isinstance(col.type, sqlalchemy.Date):
                row[col.name] = date.fromisoformat(v[:10])
        except ValueError:
            pass


@router.get("/export")
def export_data(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """导出当前账号全量数据为 JSON 备份"""
    data = {
        "version": EXPORT_VERSION,
        "exported_at": datetime.now().isoformat(),
        "username": user.username,
        "custom_options": [_serialize(o) for o in db.query(CustomOption).filter(CustomOption.user_id == user.id).all()],
        "categories": [_serialize(c) for c in db.query(Category).filter(Category.user_id == user.id).all()],
        "assets": [_serialize(a) for a in db.query(Asset).filter(Asset.user_id == user.id).all()],
        "insurance_policies": [_serialize(p) for p in db.query(InsurancePolicy).filter(InsurancePolicy.user_id == user.id).all()],
        "accounts": [_serialize(a) for a in db.query(Account).filter(Account.user_id == user.id).all()],
        "investment_accounts": [_serialize(a) for a in db.query(InvestmentAccount).filter(InvestmentAccount.user_id == user.id).all()],
        "investment_flows": [_serialize(f) for f in db.query(InvestmentFlow).filter(InvestmentFlow.user_id == user.id).all()],
        "asset_valuations": [_serialize(v) for v in db.query(AssetValuation).filter(AssetValuation.user_id == user.id).all()],
        "account_transactions": [_serialize(t) for t in db.query(AccountTransaction).filter(AccountTransaction.user_id == user.id).all()],
        "daily_pnl": [_serialize(p) for p in db.query(DailyPnl).filter(DailyPnl.user_id == user.id).all()],
        "transfers": [_serialize(t) for t in db.query(Transfer).filter(Transfer.user_id == user.id).all()],
        "loans": [_serialize(l) for l in db.query(Loan).filter(Loan.user_id == user.id).all()],
        "loan_payments": [_serialize(p) for p in db.query(LoanPayment).filter(LoanPayment.user_id == user.id).all()],
        "policy_payments": [_serialize(p) for p in db.query(PolicyPayment).filter(PolicyPayment.user_id == user.id).all()],
        "transaction_templates": [_serialize(t) for t in db.query(TransactionTemplate).filter(TransactionTemplate.user_id == user.id).all()],
        "scheduled_transactions": [_serialize(s) for s in db.query(ScheduledTransaction).filter(ScheduledTransaction.user_id == user.id).all()],
        "transactions": [_serialize(t) for t in db.query(Transaction).filter(Transaction.user_id == user.id).all()],
        "attachments": [_serialize(a) for a in db.query(Attachment).filter(Attachment.user_id == user.id).all()],
        "reminder_rules": [_serialize(r) for r in db.query(ReminderRule).filter(ReminderRule.user_id == user.id).all()],
    }
    return data


class ImportPayload(BaseModel):
    data: dict


@router.post("/import")
def import_data(body: ImportPayload, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """导入 JSON 备份（覆盖当前账号全部数据）"""
    data = body.data
    if not data or data.get("version") != EXPORT_VERSION:
        raise HTTPException(status_code=400, detail="无效的备份文件格式")

    # 1. 清空当前账号数据
    delete_user_data(db, user.id)
    db.flush()

    # 2. 重建父表，记录 old_id -> new_id 映射
    id_maps = {}
    for model in _PARENT_MODELS:
        key = model.__tablename__
        id_maps[key] = {}
        for row in data.get(key, []):
            row = dict(row)
            old_id = row.pop("id", None)
            row.pop("user_id", None)
            _convert_cols(model, row)
            # 账户外键映射（资产/保单/借款的 account_id、投资账户的 cash_account_id）
            for fk_col in ("account_id", "cash_account_id"):
                if fk_col in row and row[fk_col] is not None:
                    row[fk_col] = id_maps.get("accounts", {}).get(row[fk_col])
            obj = model(**row, user_id=user.id)
            db.add(obj)
            db.flush()
            if old_id is not None:
                id_maps[key][old_id] = obj.id

    # 3. 重建子表（外键按映射转换）
    for model in _CHILD_MODELS:
        key = model.__tablename__
        for row in data.get(key, []):
            row = dict(row)
            row.pop("id", None)
            row.pop("user_id", None)
            _convert_cols(model, row)
            # 外键映射
            for fk_col in ("asset_id", "account_id", "investment_account_id", "category_id",
                           "from_account_id", "to_account_id", "loan_id", "policy_id"):
                if fk_col in row and row[fk_col] is not None:
                    parent_key = {
                        "asset_id": "assets",
                        "account_id": "accounts",
                        "investment_account_id": "investment_accounts",
                        "category_id": "categories",
                        "from_account_id": "accounts",
                        "to_account_id": "accounts",
                        "loan_id": "loans",
                        "policy_id": "insurance_policies",
                    }[fk_col]
                    row[fk_col] = id_maps.get(parent_key, {}).get(row[fk_col])
            try:
                obj = model(**row, user_id=user.id)
                db.add(obj)
            except TypeError:
                continue

    # 4. 重建附件（record_id 按模块映射到新 id）
    module_to_table = {
        "transaction": "transactions",
        "loan": "loans",
        "insurance": "insurance_policies",
        "asset": "assets",
        "financial": "investment_accounts",
        "account": "accounts",
    }
    for row in data.get("attachments", []):
        row = dict(row)
        row.pop("id", None)
        row.pop("user_id", None)
        rid = row.get("record_id")
        if rid is not None:
            table = module_to_table.get(row.get("module"))
            if table:
                row["record_id"] = id_maps.get(table, {}).get(rid)
        try:
            db.add(Attachment(**row, user_id=user.id))
        except TypeError:
            continue

    # 5. 重建提醒规则（不含已读记录，导入后重新提醒）
    for row in data.get("reminder_rules", []):
        row = dict(row)
        row.pop("id", None)
        row.pop("user_id", None)
        try:
            db.add(ReminderRule(**row, user_id=user.id))
        except TypeError:
            continue

    db.commit()
    return {"ok": True, "message": "数据导入成功（覆盖当前账号）"}
