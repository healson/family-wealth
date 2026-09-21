from datetime import datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def now():
    return datetime.now()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    is_admin: Mapped[int] = mapped_column(default=0)  # 1=管理员（可管理账号），0=普通成员
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class CustomOption(Base):
    """用户自定义分类/类别选项（固定资产类别、保单险种、账户类型、投资类型等）"""

    __tablename__ = "custom_options"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1, index=True)
    module: Mapped[str] = mapped_column(String(50))  # asset_category / insurance_category / account_type / financial_type
    value: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AISetting(Base):
    """AI 模型配置（按账号保存，页面可视化设置）"""

    __tablename__ = "ai_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1, index=True, unique=True)
    base_url: Mapped[str] = mapped_column(String(200), default="https://api.openai.com/v1")
    api_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    model: Mapped[str] = mapped_column(String(100), default="gpt-4o-mini")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class Asset(Base):
    """固定资产：房产、车辆、收藏品等"""

    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1, index=True)
    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(20), default="房产")  # 房产/车辆/收藏品/其他
    purchase_price: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    purchase_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    current_value: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    valuation_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    loan_balance: Mapped[float] = mapped_column(Numeric(18, 2), default=0)  # 贷款余额（负债）
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True)  # 购入付款账户（强关联，全款部分从该账户扣款）
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    valuations: Mapped[list["AssetValuation"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan", order_by="AssetValuation.date"
    )


class AssetValuation(Base):
    """固定资产历史估值，用于价值变化趋势"""

    __tablename__ = "asset_valuations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1, index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    value: Mapped[float] = mapped_column(Numeric(18, 2))
    date: Mapped[datetime] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)

    asset: Mapped[Asset] = relationship(back_populates="valuations")


class InsurancePolicy(Base):
    """保单管理"""

    __tablename__ = "insurance_policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1, index=True)
    company: Mapped[str] = mapped_column(String(100))  # 保险公司
    product_name: Mapped[str] = mapped_column(String(100))  # 产品名称
    policy_no: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 保单号
    category: Mapped[str] = mapped_column(String(20), default="寿险")  # 寿险/健康险/意外险/车险/家财险/年金险/其他
    insured_person: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 被保人
    premium: Mapped[float] = mapped_column(Numeric(18, 2), default=0)  # 保费
    coverage: Mapped[float] = mapped_column(Numeric(18, 2), default=0)  # 保额
    pay_method: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 趸交/年缴/半年缴/季缴/月缴
    start_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)  # 投保日期
    end_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)  # 到期日期
    next_due_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)  # 下一缴费日
    last_paid_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)  # 最近一次缴费日（缴费闭环用）
    beneficiary: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 受益人
    status: Mapped[str] = mapped_column(String(20), default="有效")  # 有效/已到期/已退保
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True)  # 缴费账户（强关联，保费从该账户支出）
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    payments: Mapped[list["PolicyPayment"]] = relationship(
        back_populates="policy", cascade="all, delete-orphan", order_by="PolicyPayment.date"
    )


class PolicyPayment(Base):
    """保单缴费记录：每次「缴费」动作生成一条（余额对账与资金流水依据）"""

    __tablename__ = "policy_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1, index=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("insurance_policies.id", ondelete="CASCADE"), index=True)
    # 缴费账户快照：记录本笔保费实际从哪个账户扣款。
    # 必须自带（不可用 policy.account_id 反推）——否则一旦改保单缴费账户，
    # 历史缴费会被整体重新归属到新账户，导致新旧账户余额对账同时失衡。
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    amount: Mapped[float] = mapped_column(Numeric(18, 2))
    date: Mapped[datetime] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)

    policy: Mapped[InsurancePolicy] = relationship(back_populates="payments")


class Account(Base):
    """现金/银行存款账户"""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1, index=True)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(20), default="活期存款")  # 现金/活期存款/定期存款/货币基金/信用卡/其他
    bucket: Mapped[str] = mapped_column(String(20), default="emergency")  # 资金用途：emergency 应急/stable 稳健/long_term 长期
    balance: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    initial_balance: Mapped[float] = mapped_column(Numeric(18, 2), default=0)  # 期初基准余额（余额对账校验用）
    institution: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 开户机构
    opening_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    transactions: Mapped[list["AccountTransaction"]] = relationship(
        back_populates="account", cascade="all, delete-orphan", order_by="AccountTransaction.date"
    )


class AccountTransaction(Base):
    """账户存取流水"""

    __tablename__ = "account_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1, index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(10))  # 存入/取出
    amount: Mapped[float] = mapped_column(Numeric(18, 2))
    date: Mapped[datetime] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)

    account: Mapped[Account] = relationship(back_populates="transactions")


class InvestmentAccount(Base):
    """投资账户：记录各投资账户日盈亏，不管理复杂持仓"""

    __tablename__ = "investment_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1, index=True)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(20), default="券商")  # 券商/基金/银行理财/其他
    bucket: Mapped[str] = mapped_column(String(20), default="long_term")  # 资金用途：emergency 应急/stable 稳健/long_term 长期
    balance: Mapped[float] = mapped_column(Numeric(18, 2), default=0)  # 当前总市值（联动维护：记账初值 + 累计盈亏 ± 累计转入/转出）
    cash_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True)  # 关联现金账户（转入/转出资金来源）
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    pnl_records: Mapped[list["DailyPnl"]] = relationship(
        back_populates="account", cascade="all, delete-orphan", order_by="DailyPnl.date"
    )


class InvestmentFlow(Base):
    """投资资金流水：转入（现金→投资）/ 转出（投资→现金），联动账户余额"""

    __tablename__ = "investment_flows"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1, index=True)
    investment_account_id: Mapped[int] = mapped_column(ForeignKey("investment_accounts.id", ondelete="CASCADE"), index=True)
    # 关联现金账户快照：记录本笔资金实际进出的现金账户。
    # 必须自带（不可用 investment_account.cash_account_id 反推）——否则一旦改关联现金账户，
    # 历史流水会被整体重新归属到新账户，导致新旧账户余额对账同时失衡。
    cash_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(String(10))  # 转入/转出
    amount: Mapped[float] = mapped_column(Numeric(18, 2))
    date: Mapped[datetime] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)


class DailyPnl(Base):
    """投资账户日盈亏记录（正=盈利，负=亏损）"""

    __tablename__ = "daily_pnl"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1, index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("investment_accounts.id", ondelete="CASCADE"))
    date: Mapped[datetime] = mapped_column(Date)
    pnl: Mapped[float] = mapped_column(Numeric(18, 2))  # 盈亏金额，可为负
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)

    account: Mapped[InvestmentAccount] = relationship(back_populates="pnl_records")


class Transfer(Base):
    """账户间转账记录：转账时自动同步两个账户余额"""

    __tablename__ = "transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1, index=True)
    from_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    to_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    amount: Mapped[float] = mapped_column(Numeric(18, 2))
    date: Mapped[datetime] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    from_account: Mapped[Account] = relationship(foreign_keys=[from_account_id])
    to_account: Mapped[Account] = relationship(foreign_keys=[to_account_id])


class Category(Base):
    """收支分类"""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1, index=True)
    name: Mapped[str] = mapped_column(String(50))
    type: Mapped[str] = mapped_column(String(10))  # 收入/支出
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)


class Loan(Base):
    """借款管理：借出（应收款）/ 借入（应付款）"""

    __tablename__ = "loans"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1, index=True)
    type: Mapped[str] = mapped_column(String(10))  # 借出/借入
    counterparty: Mapped[str] = mapped_column(String(100))  # 对方（借款人/出借人）
    amount: Mapped[float] = mapped_column(Numeric(18, 2))
    date: Mapped[datetime] = mapped_column(Date)  # 借款日期
    due_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)  # 约定还款日
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="未结清")  # 未结清/已结清
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True)  # 借出/借入发生账户（强关联）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    payments: Mapped[list["LoanPayment"]] = relationship(
        back_populates="loan", cascade="all, delete-orphan", order_by="LoanPayment.date"
    )


class LoanPayment(Base):
    """借款还款/收款流水"""

    __tablename__ = "loan_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1, index=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id", ondelete="CASCADE"))
    amount: Mapped[float] = mapped_column(Numeric(18, 2))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True)  # 收款/还款账户（强关联）
    date: Mapped[datetime] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)

    loan: Mapped[Loan] = relationship(back_populates="payments")


class TransactionTemplate(Base):
    """交易模板：常用记账一键套用"""

    __tablename__ = "transaction_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1, index=True)
    name: Mapped[str] = mapped_column(String(100))  # 模板名称
    type: Mapped[str] = mapped_column(String(10))  # 收入/支出
    amount: Mapped[float] = mapped_column(Numeric(18, 2))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    category: Mapped[Category | None] = relationship()
    account: Mapped[Account | None] = relationship()


class ScheduledTransaction(Base):
    """定时交易：到点自动生成收支记录"""

    __tablename__ = "scheduled_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1, index=True)
    name: Mapped[str] = mapped_column(String(100))  # 任务名称
    type: Mapped[str] = mapped_column(String(10))  # 收入/支出
    amount: Mapped[float] = mapped_column(Numeric(18, 2))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    frequency: Mapped[str] = mapped_column(String(10))  # monthly / weekly / yearly
    day: Mapped[int] = mapped_column(default=1)  # monthly: 1-28；weekly: 0-6（周一~周日）；yearly: 月内日
    yearly_month: Mapped[int | None] = mapped_column(nullable=True)  # yearly 时：1-12
    start_date: Mapped[datetime] = mapped_column(Date)  # 生效起始日
    end_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)  # 可空=长期
    active: Mapped[int] = mapped_column(default=1)  # 1=启用 0=停用
    next_run_date: Mapped[datetime] = mapped_column(Date)  # 下次执行日
    last_run_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    category: Mapped[Category | None] = relationship()
    account: Mapped[Account | None] = relationship()


class Transaction(Base):
    """日常收支"""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1, index=True)
    type: Mapped[str] = mapped_column(String(10))  # 收入/支出
    amount: Mapped[float] = mapped_column(Numeric(18, 2))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    date: Mapped[datetime] = mapped_column(Date)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    category: Mapped[Category | None] = relationship()
    account: Mapped[Account | None] = relationship()


class Attachment(Base):
    """附件：图片/文档，关联到某模块的某条记录（module + record_id）"""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1, index=True)
    module: Mapped[str] = mapped_column(String(30))  # transaction/loan/insurance/asset/financial/account
    record_id: Mapped[int | None] = mapped_column(nullable=True, index=True)  # 关联记录 id（上传时可为空，保存后关联）
    filename: Mapped[str] = mapped_column(String(255))  # 原始文件名
    stored_name: Mapped[str] = mapped_column(String(255))  # 磁盘存储名（uuid + 扩展名）
    mime: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    size: Mapped[int] = mapped_column(default=0)  # 字节
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ReminderRule(Base):
    """续期/到期提醒规则：在到期前 lead_days 天内弹出提醒（可在设置管理中增删改）"""

    __tablename__ = "reminder_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1, index=True)
    label: Mapped[str] = mapped_column(String(50), default="")  # 如：提前1个月
    lead_days: Mapped[int] = mapped_column(default=7)  # 提前天数（30=月/7=周/3/2/1 天）
    scope: Mapped[str] = mapped_column(String(20), default="all")  # all / insurance / loan
    enabled: Mapped[int] = mapped_column(default=1)  # 1=启用 0=停用
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ReminderDismissal(Base):
    """提醒已读记录：用户对某条（规则+记录+到期日）提醒点「已知晓」后不再弹出"""

    __tablename__ = "reminder_dismissals"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1, index=True)
    rule_id: Mapped[int] = mapped_column(index=True)
    module: Mapped[str] = mapped_column(String(30))
    record_id: Mapped[int] = mapped_column()
    due_date: Mapped[str] = mapped_column(String(20))  # 到期日字符串，绑定该次到期
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    __table_args__ = (
        # 同一用户对（规则+记录+到期日）只记一次
        UniqueConstraint("user_id", "rule_id", "module", "record_id", "due_date", name="uq_reminder_dismissal"),
    )


class DeletedRecord(Base):
    """删除归档（回收站）：删记录前把原样存一份，供事后找回。

    ⚠️ 设计要点：**只写不读** —— 不参与任何查询、统计与余额对账。

    这是刻意选的方案。另一种做法是软删除（在业务表上加 `deleted_at`），但它会和
    **资金守恒**打架：`utils.collect_account_flows` 有 9 个来源，软删除后每一处
    都必须记得加 `deleted_at IS NULL`，**漏一处就静默对账失衡** —— 那恰恰是本项目
    最要紧的不变量。放在独立表里，则余额逻辑一行都不用改，9 个来源一个也不用动。

    `payload` 是被删记录自身的全部列（JSON）；`context` 是补充上下文
    （父记录标识、余额回滚了哪个账户多少金额），方便日后人工还原。
    """

    __tablename__ = "deleted_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1, index=True)
    module: Mapped[str] = mapped_column(String(40), index=True)  # 原表名，如 policy_payments
    record_id: Mapped[int | None] = mapped_column(nullable=True)  # 原记录 id（仅作标识，可能被复用）
    label: Mapped[str] = mapped_column(String(200), default="")  # 人能看懂的一行摘要
    payload: Mapped[str] = mapped_column(Text)  # 被删记录的全部列（JSON）
    context: Mapped[str | None] = mapped_column(Text, nullable=True)  # 补充上下文（JSON）
    deleted_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)

