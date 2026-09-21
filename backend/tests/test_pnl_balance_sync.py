# -*- coding: utf-8 -*-
"""投资盈亏与账户市值（balance）联动测试（v1.10.1）

背景：修复「记了很多盈亏明细，但金融总资产不变」的缺口。
原先 `DailyPnl` 只做记录、从不回写 `InvestmentAccount.balance`，
而 dashboard 的 `financial_value = sum(balance)`，
于是盈亏全部滞留在图表里、进不了总资产。

本次验证：
  1. 新增盈亏 → 账户 balance 同步增加；
  2. 删除盈亏 → balance 同步回滚；
  3. 多账户隔离（A 的盈亏不污染 B）；
  4. 正负混合与两位小数精度；
  5. 金融总资产（全部投资账户余额之和）随盈亏同步变化。
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="fw_pnl_sync_")
os.makedirs(os.path.join(TMP, "static", "assets"), exist_ok=True)
os.environ["DATA_DIR"] = TMP
os.environ["STATIC_DIR"] = os.path.join(TMP, "static")
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["TZ"] = "Asia/Shanghai"

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from datetime import date  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import init_db  # noqa: E402

_db = SessionLocal()
try:
    init_db(_db)
finally:
    _db.close()

client = TestClient(app)
_login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
assert _login.status_code == 200, _login.text
H = {"Authorization": f"Bearer {_login.json()['token']}"}

TODAY = date.today().isoformat()
_fails = []
_checks = 0


def check(name, cond, detail=""):
    global _checks
    _checks += 1
    if cond:
        print(f"  ok   {name}")
    else:
        _fails.append(f"{name}  {detail}")
        print(f"  FAIL {name}  {detail}")


def mk_account(name, balance):
    r = client.post("/api/financial",
                    json={"name": name, "type": "券商", "balance": balance}, headers=H)
    assert r.status_code == 200, (name, r.status_code, r.text)
    return r.json()["id"]


def get_balance(acc_id):
    for a in client.get("/api/financial", headers=H).json():
        if a["id"] == acc_id:
            return round(float(a["balance"]), 2)
    raise AssertionError(f"账户 {acc_id} 未找到")


def add_pnl(acc_id, pnl):
    r = client.post(f"/api/financial/{acc_id}/pnl",
                    json={"date": TODAY, "pnl": pnl, "note": "selftest"}, headers=H)
    assert r.status_code == 200, (acc_id, pnl, r.status_code, r.text)
    return r.json()["id"]


def del_pnl(acc_id, pnl_id):
    r = client.delete(f"/api/financial/{acc_id}/pnl/{pnl_id}", headers=H)
    assert r.status_code == 200, (acc_id, pnl_id, r.status_code, r.text)


def sum_balances():
    return round(sum(float(a["balance"]) for a in client.get("/api/financial", headers=H).json()), 2)


print("[1] 新增盈亏同步增加余额")
A = mk_account("自检-联动A", 1000.0)
check("初始余额 1000", get_balance(A) == 1000.0, f"got {get_balance(A)}")
add_pnl(A, 50.0)
check("记 +50 → 1050", get_balance(A) == 1050.0, f"got {get_balance(A)}")
add_pnl(A, -20.0)
check("记 -20 → 1030", get_balance(A) == 1030.0, f"got {get_balance(A)}")

print("[2] 删除盈亏回滚余额")
p = add_pnl(A, 200.0)
check("记 +200 → 1230", get_balance(A) == 1230.0, f"got {get_balance(A)}")
del_pnl(A, p)
check("删除 +200 → 1030（回滚）", get_balance(A) == 1030.0, f"got {get_balance(A)}")

print("[3] 多账户隔离")
B = mk_account("自检-联动B", 5000.0)
add_pnl(B, -100.0)
check("B 记 -100 → 4900", get_balance(B) == 4900.0, f"got {get_balance(B)}")
check("A 不受 B 影响（仍 1030）", get_balance(A) == 1030.0, f"got {get_balance(A)}")

print("[4] 两位小数精度")
C = mk_account("自检-联动C", 1000.0)
add_pnl(C, 0.01)
check("记 +0.01 → 1000.01", get_balance(C) == 1000.01, f"got {get_balance(C)}")
add_pnl(C, -0.01)
check("再记 -0.01 → 1000 归零", get_balance(C) == 1000.0, f"got {get_balance(C)}")

print("[5] 金融总资产随盈亏同步变化")
s0 = sum_balances()
add_pnl(A, 1000.0)
s1 = sum_balances()
check("总资产随 A 盈亏 +1000", round(s1 - s0, 2) == 1000.0, f"delta={round(s1 - s0, 2)}")
p2 = add_pnl(A, 1000.0)
del_pnl(A, p2)
check("删除后总资产回落", round(sum_balances() - s1, 2) == 0.0, f"delta={round(sum_balances() - s1, 2)}")

print()
print(f"共 {_checks} 项，失败 {len(_fails)} 项")
if _fails:
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("盈亏-余额联动自检全部通过 ✅")
