"""初始化：创建默认用户 + 旧库迁移 + 可选演示数据"""
import os
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from .auth import hash_password
from .models import (
    Account,
    AccountTransaction,
    Asset,
    AssetValuation,
    Category,
    DailyPnl,
    InsurancePolicy,
    InvestmentAccount,
    Transaction,
    Transfer,
    User,
)

# 旧持仓类型 → 新账户类型映射
_TYPE_MAP = {
    "股票": "券商",
    "基金": "基金",
    "债券": "券商",
    "黄金": "其他",
    "理财产品": "银行理财",
    "其他": "其他",
}


def init_db(db: Session) -> bool:
    """确保默认用户存在，返回是否全新初始化"""
    from sqlalchemy import inspect

    from .database import Base, engine

    tables_before = set(inspect(engine).get_table_names())
    Base.metadata.create_all(bind=engine)
    migrate_user_id_column(db)
    ensure_strong_link_columns(db)
    migrate_legacy_schema(db)
    if "policy_payments" not in tables_before:
        _backfill_policy_payments(db)  # 本次升级新增缴费记录表：为存量保单补一条历史缴费记录

    admin = db.query(User).filter(User.username == "admin").first()
    if admin is None:
        password = os.environ.get("ADMIN_PASSWORD", "admin123")
        db.add(User(username="admin", password_hash=hash_password(password), is_admin=1))
        db.commit()
        return True
    # 确保 admin 拥有管理员权限
    if not admin.is_admin:
        admin.is_admin = 1
        db.commit()
    return False


def _backfill_policy_payments(db: Session):
    """升级新增 policy_payments 表时：为存量保单补一条历史缴费记录。
    v1.3/v1.4 在创建保单时已从账户扣减保费，补记录保证余额对账与资金流水一致；
    新库无存量保单则跳过；此后新建保单不自动扣款，缴费由「缴费」动作触发并留痕。
    """
    from .models import PolicyPayment

    policies = db.query(InsurancePolicy).all()
    for p in policies:
        db.add(PolicyPayment(
            user_id=p.user_id, policy_id=p.id,
            amount=float(p.premium),
            date=(p.last_paid_date or p.created_at.date()),
            note="历史缴费（升级补齐）",
        ))
    if policies:
        db.commit()


# 需要 user_id 隔离的业务表（不含 users）
_USER_SCOPED_TABLES = [
    "ai_settings", "custom_options", "scheduled_transactions", "transaction_templates",
    "loan_payments", "loans", "assets", "asset_valuations",
    "insurance_policies", "accounts", "account_transactions", "investment_accounts",
    "daily_pnl", "transfers", "categories", "transactions",
]


def migrate_user_id_column(db: Session):
    """旧库迁移：为业务表补 user_id 列（旧数据默认归 admin id=1），users 表补 is_admin 列"""
    from sqlalchemy import inspect, text
    from .database import engine

    inspector = inspect(engine)
    with engine.begin() as conn:
        # users 表补 is_admin
        if "is_admin" not in {c["name"] for c in inspector.get_columns("users")}:
            conn.execute(text("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0"))
        # 业务表补 user_id（旧数据归 admin）
        for table in _USER_SCOPED_TABLES:
            if table not in inspector.get_table_names():
                continue
            cols = {c["name"] for c in inspector.get_columns(table)}
            if "user_id" not in cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER DEFAULT 1"))
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_user_id ON {table}(user_id)"))
    # 默认 admin 账号设为管理员
    admin = db.query(User).filter(User.username == "admin").first()
    if admin and not admin.is_admin:
        admin.is_admin = 1
        db.commit()


# 各版本资金强关联新增的列（SQLite：create_all 只建新表、不给旧表加列，旧库升级必须显式 ALTER 补齐）
_STRONG_LINK_COLUMNS = [
    ("accounts", "initial_balance", "NUMERIC(18,2) DEFAULT 0", True),  # (表, 列, DDL, 是否需要回填=当前余额)
    ("accounts", "bucket", "VARCHAR(20) DEFAULT 'emergency'", False),  # 资金用途：应急/稳健/长期
    ("investment_accounts", "bucket", "VARCHAR(20) DEFAULT 'long_term'", False),
    ("assets", "account_id", "INTEGER", False),
    ("insurance_policies", "account_id", "INTEGER", False),
    ("insurance_policies", "last_paid_date", "DATE", False),
    ("investment_accounts", "cash_account_id", "INTEGER", False),
    ("loans", "account_id", "INTEGER", False),
    ("loan_payments", "account_id", "INTEGER", False),
]


def ensure_strong_link_columns(db: Session):
    """幂等补齐资金强关联新增列：旧库升级时缺失则 ALTER TABLE ADD COLUMN（重复执行无副作用）"""
    from sqlalchemy import inspect, text

    from .database import engine

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, col, ddl, backfill in _STRONG_LINK_COLUMNS:
            if table not in tables:
                continue
            cols = {c["name"] for c in inspector.get_columns(table)}
            if col not in cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                if backfill and table in tables:
                    conn.execute(text(f"UPDATE {table} SET {col} = balance"))


def migrate_legacy_schema(db: Session):
    """旧版（持仓模式）→ 新版（投资账户日盈亏模式）平滑迁移：
    financial_assets 表存在时，将每条持仓转为投资账户（市值=数量×现价），并删除旧表"""
    from .database import engine

    with engine.connect() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}

    if "financial_assets" not in tables:
        return

    print("[migrate] 检测到旧版持仓数据，正在迁移为投资账户日盈亏模式...")
    rows = db.execute(text(
        "SELECT id, name, type, quantity, current_price, note FROM financial_assets"
    )).fetchall()
    for r in rows:
        balance = round((float(r.quantity or 0)) * (float(r.current_price or 0)), 2)
        new_type = _TYPE_MAP.get(r.type, "其他")
        db.add(InvestmentAccount(
            name=f"{r.name}（迁移）" if new_type == "其他" else r.name,
            type=new_type,
            balance=balance,
            note=(r.note or "") + " [由旧持仓数据迁移]" if r.note else "[由旧持仓数据迁移]",
        ))
    db.commit()

    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS financial_transactions"))
        conn.execute(text("DROP TABLE IF EXISTS financial_assets"))
        conn.commit()
    print(f"[migrate] 迁移完成：{len(rows)} 条持仓 → 投资账户")


def seed_demo(db: Session):
    """写入演示数据（仅当数据库为空且 SEED_DEMO_DATA=true）"""
    if db.query(Asset).count() > 0:
        return

    today = date.today()

    # ---------- 收支分类 ----------
    categories = [
        ("工资收入", "收入"), ("理财收益", "收入"), ("奖金", "收入"), ("其他收入", "收入"),
        ("餐饮", "支出"), ("交通", "支出"), ("居住", "支出"), ("购物", "支出"),
        ("医疗", "支出"), ("教育", "支出"), ("娱乐", "支出"), ("人情往来", "支出"), ("其他支出", "支出"),
    ]
    cat_map = {}
    for name, ctype in categories:
        c = Category(name=name, type=ctype)
        db.add(c)
        cat_map[name] = c
    db.flush()

    # ---------- 固定资产 ----------
    house = Asset(
        name="自住房产（XX小区）", category="房产", purchase_price=1_850_000,
        purchase_date=today - timedelta(days=1095), current_value=2_200_000,
        valuation_date=today - timedelta(days=30), loan_balance=600_000,
        note="购入价 185 万，2023 年 8 月贷款购入，贷款余额 60 万",
    )
    car = Asset(
        name="家用轿车", category="车辆", purchase_price=160_000,
        purchase_date=today - timedelta(days=500), current_value=110_000,
        valuation_date=today - timedelta(days=60), loan_balance=0,
        note="2025 年 4 月购入",
    )
    db.add_all([house, car])
    db.flush()

    # 房产估值历史（价值变化）
    for i in range(9, -1, -1):
        db.add(AssetValuation(
            asset_id=house.id,
            value=1_950_000 + i * 25_000,
            date=today - timedelta(days=i * 90),
            note="季度估值",
        ))
    db.add(AssetValuation(asset_id=car.id, value=150_000, date=today - timedelta(days=450), note="新车估值"))
    db.add(AssetValuation(asset_id=car.id, value=110_000, date=today - timedelta(days=60), note="年度估值"))

    # ---------- 保单 ----------
    db.add_all([
        InsurancePolicy(
            company="中国人寿", product_name="国寿福终身寿险", policy_no="GX2023-001234",
            category="寿险", insured_person="张先生", premium=8_500, coverage=500_000,
            pay_method="年缴", start_date=today - timedelta(days=800),
            end_date=today + timedelta(days=26420), next_due_date=today + timedelta(days=45),
            beneficiary="李女士", status="有效", note="终身寿险，年缴 8500 元",
        ),
        InsurancePolicy(
            company="平安保险", product_name="平安e生保（百万医疗）", policy_no="PA2024-998877",
            category="健康险", insured_person="全家", premium=1_200, coverage=4_000_000,
            pay_method="年缴", start_date=today - timedelta(days=200),
            end_date=today + timedelta(days=165), next_due_date=today + timedelta(days=165),
            beneficiary="—", status="有效", note="百万医疗险，全家共享",
        ),
        InsurancePolicy(
            company="太平洋保险", product_name="车险（交强险+商业险）", policy_no="CPIC2025-556677",
            category="车险", insured_person="家用轿车", premium=4_800, coverage=1_000_000,
            pay_method="年缴", start_date=today - timedelta(days=100),
            end_date=today + timedelta(days=265), next_due_date=today + timedelta(days=265),
            beneficiary="—", status="有效", note="含第三者责任险 100 万",
        ),
    ])

    # ---------- 现金账户 ----------
    acc_salary = Account(name="工资卡（招商银行）", type="活期存款", balance=86_500, institution="招商银行")
    acc_cash = Account(name="家庭现金", type="现金", balance=8_000, institution=None)
    acc_fd = Account(name="一年期定期存款", type="定期存款", balance=200_000, institution="建设银行", opening_date=today - timedelta(days=120))
    acc_credit = Account(name="信用卡（中信银行）", type="信用卡", balance=-3_200, institution="中信银行")
    db.add_all([acc_salary, acc_cash, acc_fd, acc_credit])
    db.flush()

    db.add_all([
        AccountTransaction(account_id=acc_salary.id, type="存入", amount=25_000, date=today - timedelta(days=20), note="8月工资"),
        AccountTransaction(account_id=acc_salary.id, type="取出", amount=12_000, date=today - timedelta(days=15), note="转入定期"),
        AccountTransaction(account_id=acc_salary.id, type="存入", amount=25_000, date=today - timedelta(days=50), note="7月工资"),
        AccountTransaction(account_id=acc_fd.id, type="存入", amount=12_000, date=today - timedelta(days=15), note="工资转入"),
    ])

    # ---------- 账户间转账 ----------
    db.add_all([
        Transfer(from_account_id=acc_salary.id, to_account_id=acc_cash.id, amount=3_000,
                 date=today - timedelta(days=10), note="取现备用"),
        Transfer(from_account_id=acc_cash.id, to_account_id=acc_credit.id, amount=3_200,
                 date=today - timedelta(days=5), note="信用卡还款"),
    ])

    # ---------- 投资账户（日盈亏模式） ----------
    inv_broker = InvestmentAccount(name="XX证券股票账户", type="券商", balance=168_000, note="主要持仓：贵州茅台")
    inv_fund = InvestmentAccount(name="支付宝基金", type="基金", balance=48_600, note="沪深300定投")
    inv_bank = InvestmentAccount(name="银行理财产品", type="银行理财", balance=112_000, note="固收+理财")
    db.add_all([inv_broker, inv_fund, inv_bank])
    db.flush()

    # 近 12 个交易日盈亏演示（正=盈利 负=亏损）
    pnl_sequences = {
        inv_broker.id: [1200, -800, 2500, -1500, 900, -600, 1800, -200, 3200, -1000, 1500, 800],
        inv_fund.id:    [300, 420, -150, 600, -80, 350, 500, -220, 780, 260, -120, 420],
        inv_bank.id:    [180, 180, 190, 175, 185, 190, 178, 182, 190, 188, 182, 186],
    }
    for acc_id, seq in pnl_sequences.items():
        for i, pnl in enumerate(seq):
            # 跳过周末，每 2 天一条（近似交易日）
            d = today - timedelta(days=i * 2)
            db.add(DailyPnl(account_id=acc_id, date=d, pnl=pnl, note="当日盈亏"))

    # ---------- 日常收支（近 4 个月） ----------
    incomes = [
        ("工资收入", 25_000), ("理财收益", 1_800), ("工资收入", 25_000), ("奖金", 8_000),
    ]
    expenses = [
        ("餐饮", 3_200), ("交通", 1_100), ("居住", 5_000), ("购物", 2_600),
        ("医疗", 800), ("教育", 2_000), ("娱乐", 1_500), ("人情往来", 1_200),
    ]
    for i in range(4):
        m_date = today - timedelta(days=30 * i)
        inc_name, inc_amt = incomes[i % len(incomes)]
        db.add(Transaction(type="收入", amount=inc_amt, category_id=cat_map[inc_name].id, date=m_date, account_id=acc_salary.id, note="月度收入"))
        for j, (ename, eamt) in enumerate(expenses):
            db.add(Transaction(
                type="支出", amount=round(eamt * (1 + (i % 3) * 0.05), 2),
                category_id=cat_map[ename].id, date=m_date - timedelta(days=j),
                account_id=acc_salary.id if j % 2 == 0 else acc_credit.id, note=ename,
            ))

    db.commit()
