# -*- coding: utf-8 -*-
"""全接口冒烟 + 出参类型契约测试（v1.7.9）

背景：v1.7.9 给出参模型基类 `ORMModel` 打开了 `validate_assignment`，并修掉
`_to_out` 里直接挂 ORM 对象的写法。这两处都作用在所有接口的「出参」上，所以需要
一次全接口巡检，确认：

  1. 所有读接口在**演示数据**下均返回 200（覆盖各类 Decimal 金额字段）；
  2. 写接口（新建/编辑）返回体同样正常；
  3. 全流程**不出现 Pydantic serializer warning**
     （`Expected float but got Decimal` —— 即 Decimal 绕过 float 声明的征兆）；
  4. 响应里所有金额类字段都是 JSON 数字，不存在 `"amount":"50.00"` 这类字符串。
"""
import json
import os
import sys
import tempfile
import warnings

TMP = tempfile.mkdtemp(prefix="fw_api_smoke_")
os.makedirs(os.path.join(TMP, "static", "assets"), exist_ok=True)
os.environ["DATA_DIR"] = TMP
os.environ["STATIC_DIR"] = os.path.join(TMP, "static")
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["SEED_DEMO_DATA"] = "true"      # 有数据才跑得到真实分支
os.environ["TZ"] = "Asia/Shanghai"

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from datetime import date, timedelta  # noqa: E402

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

TODAY = date.today()
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


MONEY_KEYS = {
    "amount", "balance", "premium", "coverage", "purchase_price", "current_value",
    "loan_balance", "net_value", "paid_amount", "remaining", "today_pnl", "month_pnl",
    "initial_balance", "total", "income", "expense", "receivable", "payable",
    "net_assets", "total_assets", "total_liabilities", "value", "principal",
}


def scan_money_types(node, path="", bad=None):
    """递归找出仍是字符串的金额字段（Decimal 绕过 float 声明的典型症状）"""
    if bad is None:
        bad = []
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}" if path else k
            if isinstance(v, str) and k in MONEY_KEYS:
                bad.append(f"{p}={v!r}")
            else:
                scan_money_types(v, p, bad)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            scan_money_types(v, f"{path}[{i}]", bad)
    return bad


print("=" * 68)
print("[1] 全量读接口巡检（演示数据）")
print("=" * 68)

GETS = [
    "/api/health",
    "/api/auth/me",
    "/api/auth/users",
    "/api/accounts",
    "/api/accounts/records",
    "/api/transactions",
    "/api/transactions/categories",
    "/api/transfers",
    "/api/loans",
    "/api/loans/records",
    "/api/insurance",
    "/api/assets",
    "/api/financial",
    "/api/financial/records",
    "/api/templates",
    "/api/scheduled",
    "/api/options?module=loan",
    "/api/reminders/rules",
    "/api/reminders/pending",
    "/api/dashboard/summary",
    "/api/data/export",
    "/api/ai/config",
    "/api/attachments?module=loan",
]

warned = []
with warnings.catch_warnings(record=True) as wl:
    warnings.simplefilter("always")
    bodies = {}
    for path in GETS:
        r = client.get(path, headers=H)
        bodies[path] = r
        check(f"GET {path} -> 200", r.status_code == 200,
              f"{r.status_code} {r.text[:160]}")
    warned = [str(w.message) for w in wl if "serializer" in str(w.message).lower()
              or "Expected `float` but got `Decimal`" in str(w.message)]

check("全量读接口无 serializer warning", not warned, str(warned[:3]))

print()
print("=" * 68)
print("[2] 金额字段类型巡检（不得出现字符串金额）")
print("=" * 68)
allbad = []
for path, r in bodies.items():
    if r.status_code != 200:
        continue
    try:
        data = r.json()
    except Exception:
        continue
    allbad += [f"{path} :: {x}" for x in scan_money_types(data)]
check("响应中金额字段均为数字", not allbad, str(allbad[:6]))

print()
print("=" * 68)
print("[3] 写接口返回体类型巡检")
print("=" * 68)


def _post(path, body):
    return client.post(path, headers=H, json=body)


with warnings.catch_warnings(record=True) as wl2:
    warnings.simplefilter("always")
    acc = _post("/api/accounts", {"name": "冒烟账户", "type": "活期存款", "balance": 8888.88})
    check("POST /api/accounts -> 200", acc.status_code == 200, acc.text[:160])
    aid = acc.json().get("id") if acc.status_code == 200 else None

    tx = _post("/api/transactions", {
        "type": "支出", "amount": 66.66, "date": TODAY.isoformat(),
        "account_id": aid, "note": "冒烟",
    })
    check("POST /api/transactions -> 200", tx.status_code == 200, tx.text[:160])

    loan = _post("/api/loans", {
        "type": "借出", "counterparty": "冒烟对象", "amount": 777.77,
        "date": TODAY.isoformat(), "account_id": aid,
    })
    check("POST /api/loans -> 200", loan.status_code == 200, loan.text[:160])
    lid = loan.json().get("id") if loan.status_code == 200 else None
    if lid:
        lp = _post(f"/api/loans/{lid}/payments",
                   {"amount": 77.77, "date": TODAY.isoformat(), "account_id": aid})
        check("POST /api/loans/{id}/payments -> 200", lp.status_code == 200, lp.text[:160])
        upd = client.put(f"/api/loans/{lid}", headers=H, json={"amount": 800.00})
        check("PUT /api/loans/{id} -> 200", upd.status_code == 200, upd.text[:160])

    ins = _post("/api/insurance", {
        "company": "冒烟保险", "product_name": "冒烟产品", "category": "寿险",
        "premium": 1234.56, "coverage": 100000, "start_date": TODAY.isoformat(),
        "account_id": aid,
    })
    check("POST /api/insurance -> 200", ins.status_code == 200, ins.text[:160])
    iid = ins.json().get("id") if ins.status_code == 200 else None
    if iid:
        p = _post(f"/api/insurance/{iid}/pay", {})
        check("POST /api/insurance/{id}/pay -> 200", p.status_code == 200, p.text[:160])
        check("保单缴费返回体金额为数字",
              p.status_code == 200 and isinstance(p.json().get("premium"), (int, float)),
              p.text[:160])

    ast = _post("/api/assets", {
        "name": "冒烟资产", "category": "房产", "purchase_price": 500000,
        "current_value": 520000, "loan_balance": 100000,
        "purchase_date": TODAY.isoformat(), "account_id": aid,
    })
    check("POST /api/assets -> 200", ast.status_code == 200, ast.text[:160])

    fin = _post("/api/financial", {
        "name": "冒烟投资", "type": "券商", "bucket": "稳健",
        "balance": 50000, "cash_account_id": aid,
    })
    check("POST /api/financial -> 200", fin.status_code == 200, fin.text[:160])
    fid = fin.json().get("id") if fin.status_code == 200 else None
    if fid:
        fl = _post(f"/api/financial/{fid}/flows",
                   {"type": "转入", "amount": 1000, "date": TODAY.isoformat(),
                    "cash_account_id": aid})
        check("POST /api/financial/{id}/flows -> 200", fl.status_code == 200, fl.text[:160])
        pnl = _post(f"/api/financial/{fid}/pnl",
                    {"date": TODAY.isoformat(), "pnl": 123.45})
        check("POST /api/financial/{id}/pnl -> 200", pnl.status_code == 200, pnl.text[:160])
        check("盈亏返回体 pnl 为数字",
              pnl.status_code == 200 and isinstance(pnl.json().get("pnl"), (int, float)),
              pnl.text[:160])
        pnl_list = client.get(f"/api/financial/{fid}/pnl", headers=H)
        check("GET 盈亏列表 pnl 为数字",
              pnl_list.status_code == 200
              and all(isinstance(x["pnl"], (int, float)) for x in pnl_list.json()),
              pnl_list.text[:160])
        flows = client.get(f"/api/financial/{fid}/flows", headers=H)
        check("GET 投资流水 amount 为数字",
              flows.status_code == 200
              and all(isinstance(x["amount"], (int, float)) for x in flows.json()),
              flows.text[:160])

    tr = _post("/api/transfers", {
        "from_account_id": aid, "to_account_id": aid, "amount": 1, "date": TODAY.isoformat(),
    })
    # 同账户互转应被业务拒绝，但不应 500
    check("POST /api/transfers（同账户）不为 500", tr.status_code < 500, f"{tr.status_code}")

    warned2 = [str(w.message) for w in wl2 if "serializer" in str(w.message).lower()
               or "Expected `float` but got `Decimal`" in str(w.message)]
    check("写接口全程无 serializer warning", not warned2, str(warned2[:3]))

print()
print("=" * 68)
print("[4] 写后再读：列表金额类型仍为数字且无告警")
print("=" * 68)
with warnings.catch_warnings(record=True) as wl3:
    warnings.simplefilter("always")
    for path in ("/api/loans", "/api/insurance", "/api/assets", "/api/financial",
                 "/api/dashboard/summary", "/api/accounts"):
        r = client.get(path, headers=H)
        check(f"复查 GET {path} -> 200", r.status_code == 200, f"{r.status_code}")
        bad = scan_money_types(r.json())
        check(f"复查 {path} 金额均为数字", not bad, str(bad[:3]))
    warned3 = [str(w.message) for w in wl3 if "serializer" in str(w.message).lower()
               or "Expected `float` but got `Decimal`" in str(w.message)]
    check("复查阶段无 serializer warning", not warned3, str(warned3[:3]))

print()
print("=" * 68)
if _fails:
    print(f"结果：{_checks - len(_fails)}/{_checks} 通过，{len(_fails)} 失败")
    for x in _fails:
        print("  -", x)
    sys.exit(1)
print(f"结果：全部 {_checks} 项检查通过 ✅")
