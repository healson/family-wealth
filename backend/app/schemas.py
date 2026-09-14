from datetime import date, date as DateType, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    """所有「出参」模型基类。

    `validate_assignment=True` 是关键防护：Pydantic 默认**赋值不校验**，把原始
    ORM 对象直接挂到字段上（如 `out.payments = loan.payments`）不会报错，字段里
    就留着 ORM 对象；序列化时 `Numeric` 列的 Decimal 绕过 `float` 声明，接口会
    吐出 `"amount": "50.00"` 这种字符串并伴随 serializer warning。开启赋值校验后
    同类写法会当场被强制转换（或直接报错），不再静默产出错误类型。
    """

    model_config = ConfigDict(from_attributes=True, validate_assignment=True)


# ---------- 认证 ----------
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    token: str
    username: str
    is_admin: bool = False


class UserCreate(BaseModel):
    username: str
    password: str


class UserUpdate(BaseModel):
    username: Optional[str] = None


class AdminUserUpdate(BaseModel):
    """管理员修改其他账号：用户名（可选）和/或密码（可选）"""

    username: Optional[str] = None
    password: Optional[str] = None


class AttachmentOut(ORMModel):
    id: int
    module: str
    record_id: Optional[int] = None
    filename: str
    mime: str
    size: int
    created_at: datetime


class ReminderRuleCreate(BaseModel):
    label: str
    lead_days: int
    scope: str = "all"  # all / insurance / loan
    enabled: int = 1


class ReminderRuleUpdate(BaseModel):
    label: Optional[str] = None
    lead_days: Optional[int] = None
    scope: Optional[str] = None
    enabled: Optional[int] = None


class ReminderRuleOut(ORMModel):
    id: int
    label: str
    lead_days: int
    scope: str
    enabled: int


class ReminderItemOut(BaseModel):
    rule_id: int
    rule_label: str
    module: str
    record_id: int
    title: str  # 记录标题（对方/产品名等）
    due_date: str  # 到期日 YYYY-MM-DD
    due_type: str  # 续保/缴费 / 到期 / 还款
    days_left: int


class UserOut(ORMModel):
    id: int
    username: str
    is_admin: bool
    created_at: datetime


# ---------- 固定资产 ----------
class AssetBase(BaseModel):
    name: str
    category: str = "房产"
    purchase_price: float = 0
    purchase_date: Optional[date] = None
    current_value: float = 0
    valuation_date: Optional[date] = None
    loan_balance: float = 0
    account_id: Optional[int] = None  # 购入付款账户（强关联）
    note: Optional[str] = None


class AssetCreate(AssetBase):
    pass


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    purchase_price: Optional[float] = None
    purchase_date: Optional[date] = None
    current_value: Optional[float] = None
    valuation_date: Optional[date] = None
    loan_balance: Optional[float] = None
    account_id: Optional[int] = None
    note: Optional[str] = None


class ValuationCreate(BaseModel):
    value: float
    date: date
    note: Optional[str] = None


class ValuationOut(ORMModel):
    id: int
    asset_id: int
    value: float
    date: date
    note: Optional[str] = None


class AssetOut(ORMModel):
    id: int
    name: str
    category: str
    purchase_price: float
    purchase_date: Optional[date]
    current_value: float
    valuation_date: Optional[date]
    loan_balance: float
    account_id: Optional[int] = None
    note: Optional[str]
    net_value: Optional[float] = None  # 净值 = 当前估值 - 贷款余额


# ---------- 保单 ----------
class PolicyBase(BaseModel):
    company: str
    product_name: str
    policy_no: Optional[str] = None
    category: str = "寿险"
    insured_person: Optional[str] = None
    premium: float = 0
    coverage: float = 0
    pay_method: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    next_due_date: Optional[date] = None
    last_paid_date: Optional[date] = None  # 最近一次缴费日
    beneficiary: Optional[str] = None
    status: str = "有效"
    account_id: Optional[int] = None  # 缴费账户（强关联，保费从该账户支出）
    note: Optional[str] = None


class PolicyCreate(PolicyBase):
    pass


class PolicyUpdate(BaseModel):
    company: Optional[str] = None
    product_name: Optional[str] = None
    policy_no: Optional[str] = None
    category: Optional[str] = None
    insured_person: Optional[str] = None
    premium: Optional[float] = None
    coverage: Optional[float] = None
    pay_method: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    next_due_date: Optional[date] = None
    last_paid_date: Optional[date] = None
    beneficiary: Optional[str] = None
    status: Optional[str] = None
    account_id: Optional[int] = None
    note: Optional[str] = None


class PolicyOut(ORMModel):
    id: int
    company: str
    product_name: str
    policy_no: Optional[str]
    category: str
    insured_person: Optional[str]
    premium: float
    coverage: float
    pay_method: Optional[str]
    start_date: Optional[date]
    end_date: Optional[date]
    next_due_date: Optional[date]
    last_paid_date: Optional[date] = None
    beneficiary: Optional[str]
    status: str
    account_id: Optional[int] = None
    note: Optional[str]
    days_to_due: Optional[int] = None  # 距下期缴费天数


# ---------- 现金账户 ----------
class AccountBase(BaseModel):
    name: str
    type: str = "活期存款"
    bucket: str = "emergency"  # 资金用途：emergency 应急/stable 稳健/long_term 长期
    balance: float = 0
    initial_balance: Optional[float] = None  # 期初基准余额（默认=balance）
    institution: Optional[str] = None
    opening_date: Optional[date] = None
    note: Optional[str] = None


class AccountCreate(AccountBase):
    pass


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    bucket: Optional[str] = None
    balance: Optional[float] = None
    initial_balance: Optional[float] = None
    institution: Optional[str] = None
    opening_date: Optional[date] = None
    note: Optional[str] = None


class AccountTransactionCreate(BaseModel):
    type: str  # 存入/取出
    amount: float
    date: date
    note: Optional[str] = None


class AccountTransactionOut(ORMModel):
    id: int
    account_id: int
    type: str
    amount: float
    date: date
    note: Optional[str]


class AccountOut(ORMModel):
    id: int
    name: str
    type: str
    bucket: str
    balance: float
    initial_balance: Optional[float] = None
    institution: Optional[str]
    opening_date: Optional[date]
    note: Optional[str]


# ---------- 自定义选项 ----------
class OptionCreate(BaseModel):
    module: str
    value: str


class OptionOut(ORMModel):
    id: int
    module: str
    value: str


# ---------- 借款管理 ----------
class LoanCreate(BaseModel):
    type: str  # 借出/借入
    counterparty: str
    amount: float
    date: date
    due_date: Optional[date] = None
    account_id: Optional[int] = None  # 借出/借入发生账户（强关联）
    note: Optional[str] = None


class LoanUpdate(BaseModel):
    """借款编辑入参。

    两处刻意限制（v1.7.8）：
    - **无 `type`**：类型决定资金方向（借出扣款 / 借入入账），属已发生的历史事实，不可改；
    - **无 `status`**：结清状态由「本金 − 已收/已还」服务端派生，不接受外部写入，避免状态与金额脱钩。
    `extra="forbid"` 让多余字段直接报 422 —— 此前是静默丢弃，前端会误以为「保存成功」。
    """

    model_config = ConfigDict(extra="forbid")

    counterparty: Optional[str] = None
    amount: Optional[float] = None
    date: Optional[DateType] = None
    due_date: Optional[DateType] = None
    account_id: Optional[int] = None
    note: Optional[str] = None


class LoanPaymentCreate(BaseModel):
    amount: float
    date: date
    account_id: Optional[int] = None  # 收款/还款账户（强关联）
    note: Optional[str] = None


class LoanPaymentOut(ORMModel):
    id: int
    amount: float
    date: date
    account_id: Optional[int] = None
    note: Optional[str] = None


class LoanOut(ORMModel):
    id: int
    type: str
    counterparty: str
    amount: float
    date: date
    due_date: Optional[date] = None
    account_id: Optional[int] = None
    note: Optional[str] = None
    status: str
    paid_amount: float = 0
    remaining: float = 0
    overdue: bool = False
    payments: list[LoanPaymentOut] = []


# ---------- 投资账户（日盈亏） ----------
class FinancialBase(BaseModel):
    name: str
    type: str = "券商"
    bucket: str = "long_term"  # 资金用途：emergency 应急/stable 稳健/long_term 长期
    balance: float = 0
    cash_account_id: Optional[int] = None  # 关联现金账户（转入/转出资金来源）
    note: Optional[str] = None


class FinancialCreate(FinancialBase):
    pass


class FinancialUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    bucket: Optional[str] = None
    balance: Optional[float] = None
    cash_account_id: Optional[int] = None
    note: Optional[str] = None


class InvestmentFlowCreate(BaseModel):
    type: str  # 转入/转出
    amount: float
    date: date
    note: Optional[str] = None


class InvestmentFlowOut(ORMModel):
    id: int
    investment_account_id: int
    cash_account_id: Optional[int] = None  # 本笔资金实际进出的现金账户（账户快照，改关联后仍可追溯）
    type: str
    amount: float
    date: date
    note: Optional[str] = None


class PnlCreate(BaseModel):
    date: date
    pnl: float  # 盈亏金额，可为负
    note: Optional[str] = None


class PnlOut(ORMModel):
    id: int
    account_id: int
    date: date
    pnl: float
    note: Optional[str]


class FinancialOut(ORMModel):
    id: int
    name: str
    type: str
    bucket: str
    balance: float
    note: Optional[str]
    today_pnl: Optional[float] = None  # 今日盈亏
    month_pnl: Optional[float] = None  # 本月盈亏


# ---------- 转账 ----------
class TransferCreate(BaseModel):
    from_account_id: int
    to_account_id: int
    amount: float
    date: date
    note: Optional[str] = None


class TransferOut(ORMModel):
    id: int
    from_account_id: int
    to_account_id: int
    amount: float
    date: date
    note: Optional[str]
    from_account: Optional[AccountOut]
    to_account: Optional[AccountOut]


# ---------- 日常收支 ----------
class CategoryCreate(BaseModel):
    name: str
    type: str
    icon: Optional[str] = None


class CategoryOut(ORMModel):
    id: int
    name: str
    type: str
    icon: Optional[str]


class TransactionCreate(BaseModel):
    type: str  # 收入/支出
    amount: float
    category_id: Optional[int] = None
    date: date
    account_id: Optional[int] = None
    note: Optional[str] = None


class TransactionUpdate(BaseModel):
    type: Optional[str] = None
    amount: Optional[float] = None
    category_id: Optional[int] = None
    date: Optional[DateType] = None
    account_id: Optional[int] = None
    note: Optional[str] = None


class TransactionOut(ORMModel):
    id: int
    type: str
    amount: float
    category_id: Optional[int]
    category: Optional[CategoryOut]
    date: date
    account_id: Optional[int]
    account: Optional[AccountOut]
    note: Optional[str]


# ---------- 交易模板 / 定时交易 ----------
class TemplateCreate(BaseModel):
    name: str
    type: str
    amount: float
    category_id: Optional[int] = None
    account_id: Optional[int] = None
    note: Optional[str] = None


class TemplateOut(ORMModel):
    id: int
    name: str
    type: str
    amount: float
    category_id: Optional[int]
    category: Optional[CategoryOut]
    account_id: Optional[int]
    account: Optional[AccountOut]
    note: Optional[str]


class ScheduledCreate(BaseModel):
    name: str
    type: str  # 收入/支出
    amount: float
    category_id: Optional[int] = None
    account_id: Optional[int] = None
    note: Optional[str] = None
    frequency: str  # monthly / weekly / yearly
    day: int  # monthly: 1-28；weekly: 0-6；yearly: 月内日
    yearly_month: Optional[int] = None  # yearly 时 1-12
    start_date: date
    end_date: Optional[date] = None
    active: int = 1


class ScheduledUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    amount: Optional[float] = None
    category_id: Optional[int] = None
    account_id: Optional[int] = None
    note: Optional[str] = None
    frequency: Optional[str] = None
    day: Optional[int] = None
    yearly_month: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    active: Optional[int] = None


class ScheduledOut(ORMModel):
    id: int
    name: str
    type: str
    amount: float
    category_id: Optional[int]
    category: Optional[CategoryOut]
    account_id: Optional[int]
    account: Optional[AccountOut]
    note: Optional[str]
    frequency: str
    day: int
    yearly_month: Optional[int]
    start_date: date
    end_date: Optional[date]
    active: int
    next_run_date: date
    last_run_date: Optional[date]
    frequency_label: Optional[str] = None
    next_label: Optional[str] = None
