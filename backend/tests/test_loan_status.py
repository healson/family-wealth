# -*- coding: utf-8 -*-
"""借款「类型不可改 + 结清状态同源派生」回归测试（v1.7.8，A+C 方案）

背景：编辑借款弹窗的「类型」可以点选并会随请求提交，但后端 `LoanUpdate` 没有 `type`
字段，字段被静默丢弃却返回 200 → 前端提示「保存成功」而类型未变（假成功）。同时
`status` 可被外部直接写入、改金额后又不重算，导致借款页封面（按 status 过滤）与总览
（按 remaining 判定）两处口径矛盾。

本测试固化修复后的行为：
  A. 类型不可修改，且尝试修改会得到 422（不再静默无效）
  B. 结清状态唯一由「本金 − 已收/已还」派生；改金额后自动重算；不接受外部写入
  C. 借款页与总览的应收/应付口径一致（同按 remaining 判定）
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="fw_loan_status_")
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
from app.models import Loan  # noqa: E402
from app.seed import init_db, sync_loan_status  # noqa: E402

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
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  -> {detail}")
        _fails.append(f"{name}: {detail}")


def bal(name):
    for a in client.get("/api/accounts", headers=H).json():
        if a["name"] == name:
            return round(float(a["balance"]), 2)
    return None


def get_loan(lid):
    return client.get("/api/loans", headers=H).json()


print("\n[1] 准备账户与借款")
acc = client.post("/api/accounts", headers=H, json={
    "name": "回归卡", "type": "储蓄卡", "balance": 50000, "initial_balance": 50000}).json()
A = acc["id"]
check("账户初始 50000", bal("回归卡") == 50000.0, bal("回归卡"))

r = client.post("/api/loans", headers=H, json={
    "type": "借出", "counterparty": "张三", "amount": 10000, "date": TODAY, "account_id": A})
loan = r.json()
LID = loan["id"]
check("新建借款返回 200", r.status_code == 200, r.status_code)
check("新建即未结清", loan["status"] == "未结清", loan["status"])
check("remaining = 10000", loan["remaining"] == 10000.0, loan["remaining"])
check("借出扣账户 → 40000", bal("回归卡") == 40000.0, bal("回归卡"))

print("\n[2] A：类型不可修改，且尝试修改必须明确报错（不能静默无效）")
r = client.put(f"/api/loans/{LID}", headers=H, json={"type": "借入"})
check("PUT 带 type → 422（而非静默丢弃后返回 200）", r.status_code == 422, r.status_code)
after = [l for l in get_loan(LID) if l["id"] == LID][0]
check("类型仍为借出", after["type"] == "借出", after["type"])
check("账户未被改动", bal("回归卡") == 40000.0, bal("回归卡"))

print("\n[3] C：status 不接受外部写入")
r = client.put(f"/api/loans/{LID}", headers=H, json={"status": "已结清"})
check("PUT 带 status → 422", r.status_code == 422, r.status_code)
r = client.put(f"/api/loans/{LID}", headers=H, json={"随便一个未知字段": 1})
check("PUT 带未知字段 → 422（多余字段不再被默默吞掉）", r.status_code == 422, r.status_code)
r = client.put(f"/api/loans/{LID}", headers=H, json={"amount": 0})
check("PUT amount=0 → 400", r.status_code == 400, r.status_code)

print("\n[4] C：部分收款 / 全额收款时的状态派生")
r = client.post(f"/api/loans/{LID}/payments", headers=H, json={
    "amount": 3000, "date": TODAY, "account_id": A}).json()
check("收款 3000 后仍为未结清", r["status"] == "未结清", r["status"])
check("remaining = 7000", r["remaining"] == 7000.0, r["remaining"])
check("收款入账 → 43000", bal("回归卡") == 43000.0, bal("回归卡"))

r = client.post(f"/api/loans/{LID}/payments", headers=H, json={
    "amount": 7000, "date": TODAY, "account_id": A}).json()
check("全额收满 → 已结清", r["status"] == "已结清", r["status"])
check("remaining = 0", r["remaining"] == 0.0, r["remaining"])
check("账户回到 50000", bal("回归卡") == 50000.0, bal("回归卡"))

print("\n[5] C：改金额后状态自动重算（此前会残留旧状态）")
r = client.put(f"/api/loans/{LID}", headers=H, json={"amount": 15000}).json()
check("本金 10000→15000：账户补扣 5000 → 45000", bal("回归卡") == 45000.0, bal("回归卡"))
check("已结清自动回到未结清", r["status"] == "未结清", r["status"])
check("remaining = 5000", r["remaining"] == 5000.0, r["remaining"])

r = client.put(f"/api/loans/{LID}", headers=H, json={"amount": 2000}).json()
check("改到低于已收（已收 10000）：remaining 变负", r["remaining"] == -8000.0, r["remaining"])
check("状态自动变为已结清", r["status"] == "已结清", r["status"])
check("本金回滚 → 账户 58000", bal("回归卡") == 58000.0, bal("回归卡"))

print("\n[6] C：借款页与总览口径一致（同按 remaining 判定）")
client.put(f"/api/loans/{LID}", headers=H, json={"amount": 15000})  # 回到未结清、remaining=5000
loans = get_loan(LID)
page_recv = sum(l["remaining"] for l in loans if l["remaining"] > 0 and l["type"] == "借出")
page_pay = sum(l["remaining"] for l in loans if l["remaining"] > 0 and l["type"] == "借入")
s = client.get("/api/dashboard/summary", headers=H).json()
check(f"应收一致：借款页 {page_recv} == 总览 {s['receivable']}",
      round(page_recv, 2) == round(float(s["receivable"]), 2), f"{page_recv} vs {s['receivable']}")
check(f"应付一致：借款页 {page_pay} == 总览 {s['payable']}",
      round(page_pay, 2) == round(float(s["payable"]), 2), f"{page_pay} vs {s['payable']}")

print("\n[7] 删除一笔收款后状态回退")
pay_id = loans[0]["payments"][0]["id"]
r = client.delete(f"/api/loans/{LID}/payments/{pay_id}", headers=H).json()
check("删掉 3000 那笔后 remaining=8000", r["remaining"] == 8000.0, r["remaining"])
check("状态仍为未结清", r["status"] == "未结清", r["status"])

print("\n[8] 存量矛盾数据校正（sync_loan_status 幂等）")
db = SessionLocal()
try:
    row = db.query(Loan).filter(Loan.id == LID).first()
    row.status = "已结清"          # 人为制造「remaining>0 却标已结清」的历史遗留矛盾
    db.commit()
    fixed = sync_loan_status(db)
    check("校正函数修掉 1 条矛盾数据", fixed == 1, fixed)
    check("状态被改回未结清", row.status == "未结清", row.status)
    check("重复执行幂等（第二次修 0 条）", sync_loan_status(db) == 0, "应为 0")
finally:
    db.close()

print("\n[9] 资金守恒：删除借款后账户回到初始值")
client.delete(f"/api/loans/{LID}", headers=H)
check("账户回到 50000", bal("回归卡") == 50000.0, bal("回归卡"))
check("借款已清空", len(get_loan(LID)) == 0, len(get_loan(LID)))

print("\n" + "=" * 60)
print(f"结果：{_checks - len(_fails)}/{_checks} 通过，{len(_fails)} 失败")
for f in _fails:
    print(f"  FAIL {f}")
print("=" * 60)
sys.exit(1 if _fails else 0)
