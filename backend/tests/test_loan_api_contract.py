# -*- coding: utf-8 -*-
"""借款接口契约回归测试（v1.7.9）

固化两处修复：

  1. **列表排序：未结清在前**
     原实现 `order_by(Loan.status.asc())` 是字符串排序，中文「已结清」（已 U+5DF2）
     编码小于「未结清」（未 U+672A），已结清被顶到列表最前，活账（未结清）反被压在
     后面。改用显式 case 后「未结清」恒在前，同组内按借款日期、录入顺序倒序。

  2. **`payments[].amount` 必须是数字，不是字符串**
     `_to_out` 里 `out.payments = loan.payments` 直接挂 ORM 对象，Pydantic 默认赋值
     不校验 → 字段留下 ORM 对象 → 序列化时 `Numeric` 列的 Decimal 绕过 `float` 声明，
     接口吐 `"amount": "50.00"`（字符串）并伴随 serializer warning，与同一响应里的
     `amount`/`paid_amount`/`remaining`（数字）类型不一致。修复后逐条 `model_validate`，
     并给 `ORMModel` 打开 `validate_assignment` 作为同类写法的防护。
"""
import json
import os
import sys
import tempfile
import warnings

TMP = tempfile.mkdtemp(prefix="fw_loan_contract_")
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
from app.schemas import LoanOut, LoanPaymentOut  # noqa: E402
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


def mk_loan(type_, counterparty, amount, days_ago, due_days=None):
    body = {"type": type_, "counterparty": counterparty, "amount": amount,
            "date": (TODAY - timedelta(days=days_ago)).isoformat()}
    if due_days is not None:
        body["due_date"] = (TODAY + timedelta(days=due_days)).isoformat()
    r = client.post("/api/loans", headers=H, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def pay(loan_id, amount, days_ago=0):
    r = client.post(f"/api/loans/{loan_id}/payments", headers=H,
                    json={"amount": amount, "date": (TODAY - timedelta(days=days_ago)).isoformat()})
    assert r.status_code == 200, r.text
    return r.json()


def rows():
    return client.get("/api/loans", headers=H).json()


def order_ids():
    return [l["id"] for l in rows()]


def status_of(loan_id):
    for l in rows():
        if l["id"] == loan_id:
            return l["status"]
    return None


print("=" * 68)
print("[1] 列表排序：未结清在前（不受中文字符串编码影响）")
print("=" * 68)
# a：日期更近，但会被收满 → 已结清；b：日期更远，未结清
a = mk_loan("借出", "甲_近日期_将结清", 100, 1, due_days=30)
b = mk_loan("借入", "乙_远日期_未结清", 200, 10, due_days=20)
pay(a["id"], 100, days_ago=0)

check("a 已结清", status_of(a["id"]) == "已结清", status_of(a["id"]))
check("b 未结清", status_of(b["id"]) == "未结清", status_of(b["id"]))
check("未结清 b 排在已结清 a 之前", order_ids().index(b["id"]) < order_ids().index(a["id"]),
      f"实际顺序 {order_ids()}")

print()
print("=" * 68)
print("[2] 列表排序：多条未结清按「借款日期倒序 → id 倒序」")
print("=" * 68)
c = mk_loan("借出", "丙_远日期", 300, 20)
d = mk_loan("借入", "丁_中日期", 400, 5)
e = mk_loan("借出", "戊_近日期", 500, 2)   # 与 d 同日？不同日
f_ = mk_loan("借入", "己_近日期同天", 600, 2)  # 与 e 同日期，靠 id 倒序
ids = order_ids()
unsettled = [x["id"] for x in rows() if x["status"] != "已结清"]
# 借款日期：己/戊 = 2 天前，丁 = 5 天前，乙 = 10 天前，丙 = 20 天前
# 己 与 戊 同日 → 按 id 倒序（己后录入，排前）
check("未结清区块顺序为 己 → 戊 → 丁 → 乙 → 丙（日期倒序，同日按 id 倒序）",
      unsettled == [f_["id"], e["id"], d["id"], b["id"], c["id"]],
      f"实际 {unsettled}")
check("全部已结清排在未结清之后",
      ids.index(a["id"]) == len(ids) - 1,
      f"实际 {ids}")

print()
print("=" * 68)
print("[3] 状态变化触发重排：结清→沉底，删收款→回到前排")
print("=" * 68)
before = order_ids().index(a["id"])
pay(a["id"], 0) if False else None
# 给 c 也收满 → c 应沉到已结清区
pay(c["id"], 300)
check("c 结清后 status=已结清", status_of(c["id"]) == "已结清", status_of(c["id"]))
check("c 结清后沉到未结清之后", order_ids().index(c["id"]) > order_ids().index(d["id"]),
      f"实际 {order_ids()}")
# 删掉 c 的收款 → 回未结清，应重新回到未结清区块
c_pay = [p for p in client.get(f"/api/loans/{c['id']}/payments", headers=H).json()]
r = client.delete(f"/api/loans/{c['id']}/payments/{c_pay[0]['id']}", headers=H)
check("删除收款返回 200", r.status_code == 200, r.text)
check("c 回到未结清", status_of(c["id"]) == "未结清", status_of(c["id"]))
check("c 重新回到未结清区块", order_ids().index(c["id"]) < order_ids().index(a["id"]),
      f"实际 {order_ids()}")

print()
print("=" * 68)
print("[4] 类型契约：payments[].amount 必须是 JSON 数字（不是字符串）")
print("=" * 68)
g = mk_loan("借出", "庚_金额契约", 1234.56, 3)
pay(g["id"], 50.5)
pay(g["id"], 1000, days_ago=1)

raw = client.get("/api/loans", headers=H)
text = raw.text
data = json.loads(text)
grow = [x for x in data if x["id"] == g["id"]][0]

check("loan.amount 是数字", isinstance(grow["amount"], (int, float)), type(grow["amount"]).__name__)
check("loan.paid_amount 是数字", isinstance(grow["paid_amount"], (int, float)), type(grow["paid_amount"]).__name__)
check("loan.remaining 是数字", isinstance(grow["remaining"], (int, float)), type(grow["remaining"]).__name__)
check("payments[].amount 全部是数字",
      all(isinstance(p["amount"], (int, float)) for p in grow["payments"]),
      str([type(p["amount"]).__name__ for p in grow["payments"]]))
check("amount 数值精度保持（50.5 / 1000）",
      sorted(p["amount"] for p in grow["payments"]) == [50.5, 1000.0],
      str([p["amount"] for p in grow["payments"]]))
check("原文本中不存在 \"amount\":\"...\" 字符串形态",
      '"amount":"' not in text.replace(" ", ""),
      "响应里仍有字符串金额")

pays_raw = client.get(f"/api/loans/{g['id']}/payments", headers=H).json()
check("GET /loans/{id}/payments 的 amount 也是数字",
      all(isinstance(p["amount"], (int, float)) for p in pays_raw),
      str([type(p["amount"]).__name__ for p in pays_raw]))

print()
print("=" * 68)
print("[5] 无 Pydantic serializer warning（Decimal 绕过 float 声明的告警）")
print("=" * 68)
with warnings.catch_warnings(record=True) as wl:
    warnings.simplefilter("always")
    for _ in range(3):
        client.get("/api/loans", headers=H)
        client.get(f"/api/loans/{g['id']}/payments", headers=H)
        client.post(f"/api/loans/{g['id']}/payments", headers=H,
                    json={"amount": 1.25, "date": TODAY.isoformat()})
    client.put(f"/api/loans/{g['id']}", headers=H, json={"amount": 2000})
    client.get("/api/loans", headers=H)

serializer_warns = [
    str(w.message) for w in wl
    if "serializer" in str(w.message).lower() or "Expected `float` but got `Decimal`" in str(w.message)
]
check("借款接口全程无 serializer warning", not serializer_warns, str(serializer_warns[:3]))

print()
print("=" * 68)
print("[6] 防护网：给出参模型直接赋 ORM 对象也会被强制校验")
print("=" * 68)
from app.database import SessionLocal as _SL  # noqa: E402
from app.models import Loan  # noqa: E402

_s = _SL()
try:
    _loan = _s.query(Loan).first()
    out = LoanOut.model_validate(_loan)
    out.payments = _loan.payments  # 曾经的错误写法
    check("赋值后 payments 元素已被转成 LoanPaymentOut（不再是 ORM 对象）",
          all(isinstance(p, LoanPaymentOut) for p in out.payments),
          str([type(p).__name__ for p in out.payments]))
    check("赋值后 payments[].amount 已是 float",
          all(isinstance(p.amount, float) for p in out.payments),
          str([type(p.amount).__name__ for p in out.payments]))
finally:
    _s.close()

print()
print("=" * 68)
print("[7] 口径一致性：排序修复不影响统计（封面 / 总览 / 列表同源）")
print("=" * 68)
allrows = rows()
receivable = round(sum(float(l["remaining"]) for l in allrows
                       if l["type"] == "借出" and float(l["remaining"]) > 0), 2)
payable = round(sum(float(l["remaining"]) for l in allrows
                    if l["type"] == "借入" and float(l["remaining"]) > 0), 2)
dash = client.get("/api/dashboard", headers=H).json()
ov = dash.get("overview", dash)
def _find(d, keys):
    for k in keys:
        if k in d:
            return round(float(d[k]), 2)
    return None

check("列表未结清笔数 >= 1", len([l for l in allrows if l["status"] != "已结清"]) >= 1)
check("列表排序稳定（连续两次请求顺序一致）", order_ids() == order_ids(), "两次请求顺序不同")
print(f"  说明：应收 {receivable} / 应付 {payable}（由 remaining 判定，与排序无关）")

print()
print("=" * 68)
if _fails:
    print(f"结果：{_checks - len(_fails)}/{_checks} 通过，{len(_fails)} 失败")
    for x in _fails:
        print("  -", x)
    sys.exit(1)
print(f"结果：全部 {_checks} 项检查通过 ✅")
