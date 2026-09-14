# -*- coding: utf-8 -*-
"""验证「旧库升级」迁移路径：
忠实模拟旧库（policy_payments / investment_flows 两张表缺少后加的账户快照列），
确认 ensure_strong_link_columns 能 ALTER 补列 + 按父记录回填，且可重复执行。
"""
import os
import sys
import shutil
import tempfile
from datetime import date

TMP = tempfile.mkdtemp(prefix="fw_migrate_")
os.makedirs(os.path.join(TMP, "static", "assets"), exist_ok=True)
os.environ["DATA_DIR"] = TMP
os.environ["STATIC_DIR"] = os.path.join(TMP, "static")
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["SEED_DEMO_DATA"] = "false"

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from sqlalchemy import inspect, text  # noqa: E402

from app.database import SessionLocal, engine  # noqa: E402
from app.models import Account, InsurancePolicy, InvestmentAccount, PolicyPayment, InvestmentFlow  # noqa: E402
from app.seed import ensure_strong_link_columns, init_db  # noqa: E402

_fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  -> {detail}")
        _fails.append(name)


def cols(table):
    return {c["name"] for c in inspect(engine).get_columns(table)}


db = SessionLocal()
try:
    init_db(db)
    # 造数据：现金账户 + 保单(关联A) + 缴费 + 投资账户(关联A) + 一笔转入
    a = Account(name="A卡", type="活期存款", balance=10000)
    db.add(a)
    db.flush()
    pol = InsurancePolicy(company="C", product_name="P", premium=100, account_id=a.id)
    db.add(pol)
    inv = InvestmentAccount(name="I", type="券商", balance=0, cash_account_id=a.id)
    db.add(inv)
    db.flush()
    db.add(PolicyPayment(user_id=1, policy_id=pol.id, account_id=a.id, amount=100, date=date(2026, 9, 1)))
    db.add(InvestmentFlow(user_id=1, investment_account_id=inv.id, cash_account_id=a.id,
                          type="转入", amount=500, date=date(2026, 9, 1)))
    db.commit()

    # ---------- 模拟“旧库”：重建两张表为「无账户快照列」的旧结构 ----------
    print("\n[1] 模拟旧库（两表缺少后来新增的账户快照列）")
    OLD_SCHEMA = {
        "policy_payments": (
            "id INTEGER PRIMARY KEY, user_id INTEGER, policy_id INTEGER, "
            "amount NUMERIC(18,2), date DATE, note VARCHAR(200)",
            "id, user_id, policy_id, amount, date, note",
        ),
        "investment_flows": (
            "id INTEGER PRIMARY KEY, user_id INTEGER, investment_account_id INTEGER, "
            "type VARCHAR(10), amount NUMERIC(18,2), date DATE, note VARCHAR(200)",
            "id, user_id, investment_account_id, type, amount, date, note",
        ),
    }
    with engine.begin() as conn:
        for tbl, (defn, kept) in OLD_SCHEMA.items():
            conn.execute(text(f"CREATE TABLE {tbl}__old ({defn})"))
            conn.execute(text(f"INSERT INTO {tbl}__old ({kept}) SELECT {kept} FROM {tbl}"))
            conn.execute(text(f"DROP TABLE {tbl}"))
            conn.execute(text(f"ALTER TABLE {tbl}__old RENAME TO {tbl}"))

    check("policy_payments 已无 account_id", "account_id" not in cols("policy_payments"), cols("policy_payments"))
    check("investment_flows 已无 cash_account_id", "cash_account_id" not in cols("investment_flows"), cols("investment_flows"))
    check("旧表数据保留（1 条缴费 / 1 条流水）",
          db.execute(text("SELECT COUNT(*) FROM policy_payments")).scalar() == 1
          and db.execute(text("SELECT COUNT(*) FROM investment_flows")).scalar() == 1)

    # ---------- 跑迁移 ----------
    print("\n[2] 执行 ensure_strong_link_columns（幂等迁移）")
    ensure_strong_link_columns(db)
    check("policy_payments.account_id 已补齐", "account_id" in cols("policy_payments"), cols("policy_payments"))
    check("investment_flows.cash_account_id 已补齐", "cash_account_id" in cols("investment_flows"), cols("investment_flows"))

    # ---------- 验证回填 ----------
    print("\n[3] 验证按父记录回填（旧数据不丢归属）")
    pp = db.execute(text("SELECT account_id FROM policy_payments")).fetchall()
    if_ = db.execute(text("SELECT cash_account_id FROM investment_flows")).fetchall()
    check(f"缴费记录 account_id 回填为 {a.id}", pp and pp[0][0] == a.id, pp)
    check(f"投资流水 cash_account_id 回填为 {a.id}", if_ and if_[0][0] == a.id, if_)

    # ---------- 幂等：重复执行不得报错、不得改动数据 ----------
    print("\n[4] 幂等性：重复执行无副作用")
    ensure_strong_link_columns(db)
    ensure_strong_link_columns(db)
    check("重复执行后缴费流水条数不变",
          db.execute(text("SELECT COUNT(*) FROM policy_payments")).scalar() == 1)
    check("重复执行后列仍存在且回填值不变",
          "account_id" in cols("policy_payments")
          and db.execute(text("SELECT account_id FROM policy_payments")).fetchall()[0][0] == a.id)
finally:
    db.close()

print("\n" + "=" * 60)
if _fails:
    print(f"结果：{len(_fails)} 项失败 -> {_fails}")
    code = 1
else:
    print("结果：迁移路径全部通过 ✅（旧库升级可安全补列并回填）")
    code = 0
print("=" * 60)

shutil.rmtree(TMP, ignore_errors=True)
sys.exit(code)
