# -*- coding: utf-8 -*-
"""借款编辑路径行为探针（诊断用，非断言测试）

记录 **v1.7.8（A+C 方案）之后**借款编辑的真实行为，供日后回归时人工核对；
需要严格的通过/失败断言请跑 `tests/test_loan_status.py`（32 项）。

用法：在 backend 目录执行  python tests/probe_loan_edit_type.py
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="fw_probe_")
os.makedirs(os.path.join(TMP, "static", "assets"), exist_ok=True)
os.environ["DATA_DIR"] = TMP
os.environ["STATIC_DIR"] = os.path.join(TMP, "static")
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["SEED_DEMO_DATA"] = "false"
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
H = {"Authorization": f"Bearer {_login.json()['token']}"}
TODAY = date.today().isoformat()


def bal(name):
    for a in client.get("/api/accounts", headers=H).json():
        if a["name"] == name:
            return float(a["balance"])
    return None


def loan_of(lid):
    return [l for l in client.get("/api/loans", headers=H).json() if l["id"] == lid][0]


print("=" * 74)
print("场景：真实业务是「我借给张三 10000」，录入时错选成「借入」，用户想改成「借出」")
print("=" * 74)

acc = client.post("/api/accounts", headers=H, json={
    "name": "探针卡", "type": "储蓄卡", "balance": 50000, "initial_balance": 50000}).json()
A = acc["id"]
print(f"\n初始账户余额：{bal('探针卡')}")

loan = client.post("/api/loans", headers=H, json={
    "type": "借入", "counterparty": "张三", "amount": 10000,
    "date": TODAY, "account_id": A}).json()
LID = loan["id"]
print(f"[1] 录入 type={loan['type']}（出错）→ 账户 {bal('探针卡')}（借入使账户入账 +10000）")

# ---- 编辑时改类型：现在会明确报错，而不是「提示保存成功但其实没改」 ----
r = client.put(f"/api/loans/{LID}", headers=H, json={
    "type": "借出", "counterparty": "张三", "amount": 10000,
    "date": TODAY, "due_date": None, "account_id": A, "note": None})
print(f"[2] 编辑时把类型改成「借出」→ HTTP {r.status_code}"
      f"  {'[OK] 明确拒绝，不再假成功' if r.status_code == 422 else '[!!] 意外：本应变 422'}")
print(f"    类型仍为 {loan_of(LID)['type']}，账户仍 {bal('探针卡')}（未被静默改动）")
print("    前端同步：编辑弹窗的「类型」已置灰，并提示需删除后重新新增")

# ---- 唯一正确的修法：删除后重新新增（删除会逐笔回滚已发生的收款/还款） ----
print("\n[3] 正确修法：删除该笔后按正确类型重新新增")
client.post(f"/api/loans/{LID}/payments", headers=H, json={"amount": 3000, "date": TODAY, "account_id": A})
print(f"    （先模拟一笔已发生的收款 3000 → 账户 {bal('探针卡')}）")
before = bal("探针卡")
client.delete(f"/api/loans/{LID}", headers=H)
print(f"    删除借款 → 账户 {before} → {bal('探针卡')}（逐笔回滚收款 + 本金，精确回到 50000）")
fixed = client.post("/api/loans", headers=H, json={
    "type": "借出", "counterparty": "张三", "amount": 10000,
    "date": TODAY, "account_id": A}).json()
print(f"    重新新增 type={fixed['type']} → 账户 {bal('探针卡')}（借出出账 −10000，方向正确）"
      f"，status={fixed['status']}")

# ---- 状态唯一派生：不接受外部写入，改金额后自动重算 ----
print("\n[4] 结清状态：唯一由「本金 − 已收/已还」派生")
r = client.put(f"/api/loans/{fixed['id']}", headers=H, json={"status": "已结清"})
print(f"    直接写 status → HTTP {r.status_code}"
      f"  {'[OK] 拒绝外部写入' if r.status_code == 422 else '[!!] 意外'}")
o = client.post(f"/api/loans/{fixed['id']}/payments", headers=H, json={
    "amount": 10000, "date": TODAY, "account_id": A}).json()
print(f"    收满 10000 → status={o['status']} remaining={o['remaining']}")
o = client.put(f"/api/loans/{fixed['id']}", headers=H, json={"amount": 15000}).json()
print(f"    改为 15000 → status={o['status']} remaining={o['remaining']}"
      f"（自动回到未结清，此前会残留「已结清」）")
o = client.put(f"/api/loans/{fixed['id']}", headers=H, json={"amount": 2000}).json()
print(f"    改到低于已收（已收 10000）→ status={o['status']} remaining={o['remaining']}")

# ---- 两处口径一致 ----
print("\n[5] 借款页与总览口径一致（同按 remaining 判定）")
loans = client.get("/api/loans", headers=H).json()
page_recv = sum(l["remaining"] for l in loans if l["remaining"] > 0 and l["type"] == "借出")
page_pay = sum(l["remaining"] for l in loans if l["remaining"] > 0 and l["type"] == "借入")
s = client.get("/api/dashboard/summary", headers=H).json()
_same = (round(page_recv, 2) == round(float(s["receivable"]), 2)
         and round(page_pay, 2) == round(float(s["payable"]), 2))
print(f"    借款页封面：应收 {page_recv} / 应付 {page_pay}")
print(f"    财富总览　：应收 {s['receivable']} / 应付 {s['payable']}  {'[OK] 一致' if _same else '[!!] 不一致'}")

print("\n[6] 资金守恒")
client.delete(f"/api/loans/{fixed['id']}", headers=H)
print(f"    删除全部借款 → 账户 {bal('探针卡')}（应回到初始 50000）")
print("=" * 74)
