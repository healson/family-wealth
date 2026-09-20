# -*- coding: utf-8 -*-
"""数据导出的**唯一实现**（手动导出与自动备份共用）。

单独成模块（而不是放在 `routers/data_io.py` 里）的原因：
自动备份（`app/backup.py`）也要产出同样格式的 JSON，但它**不应该 import 一个 router**
—— 那会绕一圈把 FastAPI 的路由依赖带进后台线程。这个模块只依赖 models，谁都能用。

格式约定：`{"version": EXPORT_VERSION, ...各表列表...}`，按账号隔离。
`serialize` 把所有日期/时间序列化成 ISO 字符串，因此产物可直接 JSON 落盘。
"""
from datetime import date, datetime

import sqlalchemy

from .models import (
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
    ReminderRule,
    ScheduledTransaction,
    Transaction,
    TransactionTemplate,
    Transfer,
)
from .utils import jsonable

EXPORT_VERSION = 1

# 各表的导出顺序（先父后子；Account 放最前以便导入时映射账户外键）
PARENT_MODELS = [
    Account, CustomOption, Category, Asset, InsurancePolicy,
    InvestmentAccount, Loan, TransactionTemplate, ScheduledTransaction,
]
CHILD_MODELS = [
    InvestmentFlow, PolicyPayment, AssetValuation, AccountTransaction,
    DailyPnl, Transfer, Transaction, LoanPayment,
]

# 导出里出现的全部业务表名（父 + 子），供备份校验判断「像不像一份完整备份」
BUSINESS_TABLES = [m.__tablename__ for m in PARENT_MODELS + CHILD_MODELS]


def serialize(model_obj) -> dict:
    """把一行 ORM 对象转成可 JSON 落盘的 dict。

    用 `utils.jsonable` 统一处理 Decimal（Numeric 金额列）与日期时间 ——
    缺了它，`json.dump` 会在自动备份时抛 `Object of type Decimal is not JSON serializable`。
    """
    return {col.name: jsonable(getattr(model_obj, col.name)) for col in model_obj.__table__.columns}


def convert_cols(model, row: dict):
    """导入用：把字符串形式的日期/时间列转回 Python 类型。"""
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


# 导出字段 → 表名的顺序（与 build_export 的键一一对应）
_EXPORT_SPEC = [
    ("custom_options", CustomOption),
    ("categories", Category),
    ("assets", Asset),
    ("insurance_policies", InsurancePolicy),
    ("accounts", Account),
    ("investment_accounts", InvestmentAccount),
    ("investment_flows", InvestmentFlow),
    ("asset_valuations", AssetValuation),
    ("account_transactions", AccountTransaction),
    ("daily_pnl", DailyPnl),
    ("transfers", Transfer),
    ("loans", Loan),
    ("loan_payments", LoanPayment),
    ("policy_payments", PolicyPayment),
    ("transaction_templates", TransactionTemplate),
    ("scheduled_transactions", ScheduledTransaction),
    ("transactions", Transaction),
    ("attachments", Attachment),
    ("reminder_rules", ReminderRule),
]


def build_export(db, user) -> dict:
    """导出单个账号的全量数据。手动导出接口与自动备份都走这里。"""
    data = {
        "version": EXPORT_VERSION,
        "exported_at": datetime.now().isoformat(),
        "username": user.username,
    }
    for key, model in _EXPORT_SPEC:
        rows = db.query(model).filter(model.user_id == user.id).all()
        data[key] = [serialize(o) for o in rows]
    return data


def export_stats(data: dict) -> dict:
    """统计一份导出里各表条数（备份校验与界面展示用）。"""
    return {k: len(v) for k, v in data.items() if isinstance(v, list)}
