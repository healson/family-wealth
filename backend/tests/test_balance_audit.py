# -*- coding: utf-8 -*-
"""family-wealth 收支逻辑审计 —— 端到端回归测试

覆盖：收支增删改联动、转账、借款/收款、保单缴费与删除、固定资产全款部分、
投资转入与账户删除回滚、定时交易立即执行、账单导入「不计收支」过滤、
MCP 记账强制账户、以及最终「余额对账」必须全部为 0 差异。
"""
import os
import sys
import shutil
import tempfile

TMP = tempfile.mkdtemp(prefix="fw_audit_")
os.makedirs(os.path.join(TMP, "static", "assets"), exist_ok=True)
os.environ["DATA_DIR"] = TMP
os.environ["STATIC_DIR"] = os.path.join(TMP, "static")
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["TZ"] = "Asia/Shanghai"

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from datetime import date, timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import init_db  # noqa: E402

# ---------- 初始化 ----------
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


def get(path):
    r = client.get(path, headers=H)
    assert r.status_code == 200, f"GET {path} -> {r.status_code} {r.text[:300]}"
    return r.json()


def post(path, payload=None):
    r = client.post(path, headers=H, json=payload if payload is not None else {})
    assert r.status_code < 300, f"POST {path} -> {r.status_code} {r.text[:300]}"
    return r.json()


def put(path, payload):
    r = client.put(path, headers=H, json=payload)
    assert r.status_code < 300, f"PUT {path} -> {r.status_code} {r.text[:300]}"
    return r.json()


def delete(path):
    r = client.delete(path, headers=H)
    assert r.status_code < 300, f"DELETE {path} -> {r.status_code} {r.text[:300]}"
    return r.json()


def acct_map():
    return {a["name"]: a for a in get("/api/accounts")}


def bal(name):
    return round(float(acct_map()[name]["balance"]), 2)


def recon_diffs():
    s = get("/api/dashboard/summary")
    return {r["name"]: r["diff"] for r in s["reconciliation"]}


# ---------- 1. 建账户 ----------
print("\n[1] 建账户（期初基准自动 = 当前余额）")
A = post("/api/accounts", {"name": "测试卡A", "type": "活期存款", "balance": 10000})
B = post("/api/accounts", {"name": "测试卡B", "type": "活期存款", "balance": 5000})
check("账户A 初始余额 10000", bal("测试卡A") == 10000, bal("测试卡A"))
check("账户A 期初基准 = 余额", float(A["initial_balance"]) == 10000, A["initial_balance"])
check("账户初始对账无差异", all(v == 0 for v in recon_diffs().values()), recon_diffs())

# ---------- 2. 收支增 / 改 / 删 ----------
print("\n[2] 收支记录：收入 + / 支出 − / 修改回滚 / 删除回滚")
post("/api/transactions", {"type": "收入", "amount": 3000, "date": TODAY, "account_id": A["id"], "note": "工资"})
check("记收入 3000 -> 13000", bal("测试卡A") == 13000, bal("测试卡A"))

e = post("/api/transactions", {"type": "支出", "amount": 500, "date": TODAY, "account_id": A["id"], "note": "餐饮"})
check("记支出 500 -> 12500", bal("测试卡A") == 12500, bal("测试卡A"))

put(f"/api/transactions/{e['id']}", {"amount": 800})
check("支出改 800 -> 12200", bal("测试卡A") == 12200, bal("测试卡A"))

put(f"/api/transactions/{e['id']}", {"type": "收入"})
check("支出改为收入 -> 13800", bal("测试卡A") == 13800, bal("测试卡A"))

put(f"/api/transactions/{e['id']}", {"type": "支出"})
check("改回支出 -> 12200", bal("测试卡A") == 12200, bal("测试卡A"))

delete(f"/api/transactions/{e['id']}")
check("删除支出 -> 13000", bal("测试卡A") == 13000, bal("测试卡A"))

# 换账户：应从 A 回滚、记到 B
t = post("/api/transactions", {"type": "支出", "amount": 1000, "date": TODAY, "account_id": A["id"]})
check("A 支出 1000 -> 12000", bal("测试卡A") == 12000, bal("测试卡A"))
put(f"/api/transactions/{t['id']}", {"account_id": B["id"]})
check("换账户后 A 回到 13000", bal("测试卡A") == 13000, bal("测试卡A"))
check("换账户后 B 扣到 4000", bal("测试卡B") == 4000, bal("测试卡B"))
delete(f"/api/transactions/{t['id']}")
check("删除后 B 回到 5000", bal("测试卡B") == 5000, bal("测试卡B"))

# 无账户记账必须被拒
r = client.post("/api/transactions", headers=H, json={"type": "支出", "amount": 10, "date": TODAY})
check("REST 无账户记账被拒(400)", r.status_code == 400, r.status_code)

# ---------- 3. 转账 ----------
print("\n[3] 转账 A→B 2000")
tr = post("/api/transfers", {"from_account_id": A["id"], "to_account_id": B["id"], "amount": 2000, "date": TODAY})
check("A -> 11000", bal("测试卡A") == 11000, bal("测试卡A"))
check("B -> 7000", bal("测试卡B") == 7000, bal("测试卡B"))
delete(f"/api/transfers/{tr['id']}")
check("删除转账 A 回 13000", bal("测试卡A") == 13000, bal("测试卡A"))
check("删除转账 B 回 5000", bal("测试卡B") == 5000, bal("测试卡B"))
post("/api/transfers", {"from_account_id": A["id"], "to_account_id": B["id"], "amount": 2000, "date": TODAY})
check("重新转账 A=11000/B=7000", bal("测试卡A") == 11000 and bal("测试卡B") == 7000, (bal("测试卡A"), bal("测试卡B")))

# ---------- 4. 借款 + 收款 ----------
print("\n[4] 借出 1000（A 出账）→ 收款 400（A 入账）")
loan = post("/api/loans", {"type": "借出", "counterparty": "张三", "amount": 1000, "date": TODAY, "account_id": A["id"]})
check("借出后 A -> 10000", bal("测试卡A") == 10000, bal("测试卡A"))
post(f"/api/loans/{loan['id']}/payments", {"amount": 400, "date": TODAY, "account_id": A["id"]})
check("收款 400 后 A -> 10400", bal("测试卡A") == 10400, bal("测试卡A"))
check("借款剩余 600", get("/api/loans")[0]["remaining"] == 600, get("/api/loans")[0]["remaining"])

# ---------- 5. 保单缴费闭环 + 删除退回 ----------
print("\n[5] 保单：新建不扣款 / 缴费扣款 / 删除退回保费")
pol = post("/api/insurance", {
    "company": "测试保险", "product_name": "测试保单", "premium": 600, "coverage": 100000,
    "pay_method": "年缴", "start_date": TODAY, "next_due_date": (date.today() + timedelta(days=30)).isoformat(),
    "account_id": A["id"], "status": "有效",
})
check("新建保单不扣款 A=10400", bal("测试卡A") == 10400, bal("测试卡A"))
post(f"/api/insurance/{pol['id']}/pay")
check("缴费 600 后 A -> 9800", bal("测试卡A") == 9800, bal("测试卡A"))
delete(f"/api/insurance/{pol['id']}")
check("删除保单退回 600 -> A=10400", bal("测试卡A") == 10400, bal("测试卡A"))

# ---------- 6. 固定资产：只扣「全款部分」 ----------
print("\n[6] 固定资产：购入价 20000 贷款 12000 → 账户只扣 8000（原 bug 会扣 20000）")
asset = post("/api/assets", {
    "name": "测试车辆", "category": "车辆", "purchase_price": 20000, "purchase_date": TODAY,
    "current_value": 18000, "loan_balance": 12000, "account_id": A["id"],
})
check("A 扣 8000 -> 2400", bal("测试卡A") == 2400, bal("测试卡A"))
put(f"/api/assets/{asset['id']}", {"current_value": 17000})
check("仅改估值不影响账户 A=2400", bal("测试卡A") == 2400, bal("测试卡A"))
delete(f"/api/assets/{asset['id']}")
check("删除资产退回 8000 -> A=10400", bal("测试卡A") == 10400, bal("测试卡A"))

# ---------- 7. 投资转入 + 删除账户回滚 ----------
print("\n[7] 投资账户：转入 1000 / 删除投资账户应回滚现金")
inv = post("/api/financial", {"name": "测试投资账户", "type": "券商", "balance": 0, "cash_account_id": A["id"]})
post(f"/api/financial/{inv['id']}/flows", {"type": "转入", "amount": 1000, "date": TODAY})
check("转入后 A -> 9400", bal("测试卡A") == 9400, bal("测试卡A"))
delete(f"/api/financial/{inv['id']}")
check("删除投资账户后 A 回滚 -> 10400", bal("测试卡A") == 10400, bal("测试卡A"))
check("投资流水已清理", len(get("/api/financial")) == 0, get("/api/financial"))

# ---------- 8. 定时交易：立即执行须联动余额 ----------
print("\n[8] 定时交易「立即执行」须联动余额（原 bug 不联动）")
future = (date.today() + timedelta(days=5)).isoformat()
sch = post("/api/scheduled", {
    "name": "测试月供", "type": "支出", "amount": 300, "account_id": A["id"],
    "frequency": "monthly", "day": 1, "start_date": future, "active": 1,
})
check("定时任务首个执行日不早于生效日", sch["next_run_date"] >= future, sch["next_run_date"])
post(f"/api/scheduled/{sch['id']}/run-now")
check("立即执行扣 300 -> A=10100", bal("测试卡A") == 10100, bal("测试卡A"))

# ---------- 9. 账单导入：过滤「不计收支」 ----------
print("\n[9] 账单导入：不计收支应被剔除，收入/支出正常")
csv_text = (
    "交易时间,交易分类,交易对方,收/支,金额\n"
    "2026-09-01 10:00:00,餐饮,某餐厅,支出,100.00\n"
    "2026-09-02 11:00:00,转账,余额宝-单笔转入,不计收支,500.00\n"
    "2026-09-03 12:00:00,工资,某某公司,收入,8000.00\n"
)
parsed = post("/api/import/bills/parse", {"platform": "支付宝", "content": csv_text})
recs = parsed["records"]
check("解析出 2 条（剔除不计收支）", parsed["count"] == 2, parsed["count"])
check("存在收入 8000", any(r["type"] == "收入" and r["amount"] == 8000 for r in recs), recs)
check("不计收支 500 未混入", all(not (r["amount"] == 500 and r["type"] == "支出") for r in recs), recs)
conf = post("/api/import/bills/confirm", {"records": recs, "account_name": "测试卡A"})
check("导入 2 条", conf["imported"] == 2, conf)
check("导入后 A = 10100 - 100 + 8000 = 18000", bal("测试卡A") == 18000, bal("测试卡A"))

# ---------- 10. MCP 记账：必须带账户 ----------
print("\n[10] MCP add_transaction：无账户应报错，有账户应联动余额")
from app.mcp_server import TOOLS, _tool_add_transaction  # noqa: E402

schema = next(t for t in TOOLS if t["name"] == "add_transaction")["inputSchema"]
check("MCP schema 要求 account_id", "account_id" in schema.get("required", []), schema.get("required"))

_s = SessionLocal()
try:
    bad = _tool_add_transaction(_s, 1, "支出", 50)
    check("MCP 无账户返回 error", "error" in bad, bad)
    good = _tool_add_transaction(_s, 1, "支出", 50, account_id=A["id"])
    check("MCP 有账户成功", good.get("ok") is True, good)
finally:
    _s.close()
check("MCP 支出 50 -> A=17950", bal("测试卡A") == 17950, bal("测试卡A"))

# ---------- 11. 余额对账总校验（核心不变量） ----------
print("\n[11] 余额对账：全部账户 应有余额 == 实际余额（差异必须为 0）")
diffs = recon_diffs()
check("所有账户对账差异为 0", all(v == 0 for v in diffs.values()), diffs)

# 资金流向口径校验：投资转入计入流出、转出计入流入
s = get("/api/dashboard/summary")
cf = s["cash_flow"]
check("流入合计 = 各分项之和", round(sum(v for k, v in cf["inflow"].items() if k != "total"), 2) == cf["inflow"]["total"], cf["inflow"])
check("流出合计 = 各分项之和", round(sum(v for k, v in cf["outflow"].items() if k != "total"), 2) == cf["outflow"]["total"], cf["outflow"])
check("净流向 = 流入 − 流出", round(cf["inflow"]["total"] - cf["outflow"]["total"], 2) == cf["net"], cf)

# ---------- 12. 删除现金账户的连带清理 ----------
print("\n[12] 删除账户 B：涉及 B 的全部转账须回滚到 A（含历史未删转账）")
before_a = bal("测试卡A")
# 快照：当前所有以 B 为转入方的转账（步骤 3 的 2000 仍在，未删除）
_to_b = sum(float(t["amount"]) for t in get("/api/transfers") if t["to_account_id"] == B["id"])
post("/api/transfers", {"from_account_id": A["id"], "to_account_id": B["id"], "amount": 700, "date": TODAY})
check("转账后 A 减 700", bal("测试卡A") == round(before_a - 700, 2), bal("测试卡A"))
expect_a = round(before_a + _to_b, 2)  # 删 B 前 A 已被扣 700，删后连 700 一并退回 → A = before_a + 历史对 B 转账
delete(f"/api/accounts/{B['id']}")
check(f"删除 B 后 A 回滚全部对 B 转账（历史 {_to_b} + 本次 700），余额应为 {expect_a}",
      bal("测试卡A") == expect_a, f"got {bal('测试卡A')} expect {expect_a}")
diffs = recon_diffs()
check("删账户后剩余账户对账仍为 0", all(v == 0 for v in diffs.values()), diffs)

# ---------- 13. 中途变更「关联账户」不得导致历史流水归属漂移 ----------
print("\n[13] 变更关联账户：历史流水归属不得漂移（保单缴费账户 / 投资关联现金账户）")
C = post("/api/accounts", {"name": "测试卡C", "type": "活期存款", "balance": 1000})
a0, c0 = bal("测试卡A"), bal("测试卡C")

# 13a 保单：在 A 上缴费，再把缴费账户改成 C
pol2 = post("/api/insurance", {
    "company": "测试保险", "product_name": "换户测试保单", "premium": 300, "coverage": 50000,
    "pay_method": "年缴", "start_date": TODAY, "next_due_date": (date.today() + timedelta(days=30)).isoformat(),
    "account_id": A["id"], "status": "有效",
})
post(f"/api/insurance/{pol2['id']}/pay")
check("A 扣保费 300", bal("测试卡A") == round(a0 - 300, 2), bal("测试卡A"))
put(f"/api/insurance/{pol2['id']}", {"account_id": C["id"]})
check("换缴费账户后 C 余额未被改动", bal("测试卡C") == c0, bal("测试卡C"))
check("换缴费账户后 A 仍为缴费后余额", bal("测试卡A") == round(a0 - 300, 2), bal("测试卡A"))
d = recon_diffs()
check("换缴费账户后对账仍全为 0", all(v == 0 for v in d.values()), d)
delete(f"/api/insurance/{pol2['id']}")
check("删除保单退回【原缴费账户 A】而非新账户 C", bal("测试卡A") == a0, bal("测试卡A"))
check("C 全程未被影响", bal("测试卡C") == c0, bal("测试卡C"))

# 13b 投资：在 A 转入，再把关联现金账户改成 C
inv2 = post("/api/financial", {"name": "测试投资2", "type": "券商", "balance": 0, "cash_account_id": A["id"]})
post(f"/api/financial/{inv2['id']}/flows", {"type": "转入", "amount": 500, "date": TODAY})
check("A 扣 500", bal("测试卡A") == round(a0 - 500, 2), bal("测试卡A"))
put(f"/api/financial/{inv2['id']}", {"cash_account_id": C["id"]})
check("换关联现金账户后 C 未被改动", bal("测试卡C") == c0, bal("测试卡C"))
d = recon_diffs()
check("换关联现金账户后对账仍全为 0", all(v == 0 for v in d.values()), d)
delete(f"/api/financial/{inv2['id']}")
check("删除投资账户回滚到【原现金账户 A】", bal("测试卡A") == a0, bal("测试卡A"))
check("C 全程未被影响", bal("测试卡C") == c0, bal("测试卡C"))
d = recon_diffs()
check("全部用例跑完最终对账仍全为 0", all(v == 0 for v in d.values()), d)

# ---------- 结果 ----------
print("\n" + "=" * 60)
if _fails:
    print(f"结果：{_checks - len(_fails)}/{_checks} 通过，{len(_fails)} 项失败")
    for f in _fails:
        print("  ✗", f)
    code = 1
else:
    print(f"结果：全部 {_checks} 项检查通过 ✅")
    code = 0
print("=" * 60)

shutil.rmtree(TMP, ignore_errors=True)
sys.exit(code)
