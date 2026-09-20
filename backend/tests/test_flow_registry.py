# -*- coding: utf-8 -*-
"""资金动作口径注册表守门测试（v1.9.0）

## 为什么需要这个测试

`utils.collect_account_flows` 是**全部资金流水与余额对账的唯一口径**。新增一类资金动作
（比如以后加「贵金属交易」「股票分红」）时，如果只建了表、忘了在这个口径里取数，
后果是：**这笔钱在流水与对账里彻底消失**。它不报错、不崩，只是账不平，
而且往往几个月后才发现。

所以把口径声明化（`utils.FLOW_SOURCES`）并加一道结构守门：
凡持有账户列的表，必须在注册表里、或在显式豁免表里（豁免必须写明理由）。
新加资金动作模型却忘了登记，这个测试就会 FAIL —— 也就是 CI 会拦下来。

四层检查：
  1. **结构守门**：metadata 里每个持有账户列的表都在注册表 ∪ 豁免表里；
  2. **声明真实**：注册表里声明的表与列必须真的存在；
  3. **实现守门**：每个声明来源的模型类名必须出现在 `collect_account_flows` 源码里
     （防「登记了但没写取数」）；
  4. **功能性抽查**：演示数据实际产生的 kind 必须都是声明过的，且常见 kind 确实在跑。
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="fw_flow_registry_")
os.makedirs(os.path.join(TMP, "static", "assets"), exist_ok=True)
os.environ["DATA_DIR"] = TMP
os.environ["STATIC_DIR"] = os.path.join(TMP, "static")
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["TZ"] = "Asia/Shanghai"

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

import inspect  # noqa: E402

from app.database import Base, SessionLocal  # noqa: E402
from app.seed import init_db, seed_demo  # noqa: E402
from app.utils import (  # noqa: E402
    FLOW_EXEMPT_TABLES,
    FLOW_SOURCES,
    collect_account_flows,
)

_fails = []
_checks = 0


def check(name, cond, detail=""):
    global _checks
    _checks += 1
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s  -> %s" % (name, detail))
        _fails.append("%s: %s" % (name, detail))


def section(t):
    print()
    print("=" * 68)
    print(t)
    print("=" * 68)


# 能被认定为「账户列」的列名。新增这类列名时也要同步加进来，否则守门会漏。
ACCOUNT_COLUMNS = {"account_id", "cash_account_id", "from_account_id", "to_account_id"}

# 表名 -> 模型类（从 SQLAlchemy registry 反查，避免手写映射表再次产生漂移）
MODEL_BY_TABLE = {}
for _mapper in Base.registry.mappers:
    MODEL_BY_TABLE[_mapper.class_.__tablename__] = _mapper.class_

_FLOW_TABLE_NAMES = {s["table"] for s in FLOW_SOURCES}
_EXEMPT_TABLE_NAMES = set(FLOW_EXEMPT_TABLES)


# ===========================================================================
section("[1] 注册表自洽：声明的表与列真实存在")
declared_pairs = []
for src in FLOW_SOURCES:
    table = src["table"]
    check("%s 在模型里存在" % table, table in MODEL_BY_TABLE,
          "metadata 里没有这张表")
    if table not in MODEL_BY_TABLE:
        continue
    cols = {c.name for c in MODEL_BY_TABLE[table].__table__.columns}
    for col in src["account_columns"]:
        declared_pairs.append((table, col))
        check("%s.%s 真实存在" % (table, col), col in cols,
              "实际列：%s" % sorted(cols))
    check("%s 声明了 kind" % table, bool(src.get("kind")), "缺 kind")
    check("%s 声明了符号规则（sign）" % table, bool(src.get("sign")), "缺 sign 说明")

check("FLOW_SOURCES 至少 8 条（现有 8 类动作）", len(FLOW_SOURCES) >= 8,
      "实际 %d 条" % len(FLOW_SOURCES))
check("注册表里没有重复表名（transfers 除外，只登记一次）",
      len(_FLOW_TABLE_NAMES) == len(FLOW_SOURCES), str(sorted(_FLOW_TABLE_NAMES)))


# ===========================================================================
section("[2] 🔴 结构守门：凡持有账户列的表，必须登记或显式豁免")
unregistered = []
for table, model in sorted(MODEL_BY_TABLE.items()):
    cols = {c.name for c in model.__table__.columns}
    hit = cols & ACCOUNT_COLUMNS
    if not hit:
        continue
    if table in _FLOW_TABLE_NAMES or table in _EXEMPT_TABLE_NAMES:
        continue
    unregistered.append("%s（持有 %s）" % (table, "、".join(sorted(hit))))

check("没有未登记的资金动作表", not unregistered,
      "以下表持有账户列却既不在 FLOW_SOURCES 也不在 FLOW_EXEMPT_TABLES：\n     %s\n"
      "     → 新增资金动作时请登记到 utils.FLOW_SOURCES 并在 collect_account_flows 里取数；"
      "若它本身不产生流水，请加进 FLOW_EXEMPT_TABLES 并写明理由。"
      % "\n     ".join(unregistered))

for table, reason in sorted(FLOW_EXEMPT_TABLES.items()):
    check("豁免表 %s 存在于模型里" % table, table in MODEL_BY_TABLE, "表不存在")
    check("豁免表 %s 写明了理由" % table, bool(reason) and len(reason) >= 8, repr(reason))

check("豁免表本身不得同时出现在 FLOW_SOURCES 里（避免语义重复）",
      not (_EXEMPT_TABLE_NAMES & _FLOW_TABLE_NAMES),
      str(sorted(_EXEMPT_TABLE_NAMES & _FLOW_TABLE_NAMES)))


# ===========================================================================
section("[3] 🔴 实现守门：登记的来源必须真的在 collect_account_flows 里取数")
src_code = inspect.getsource(collect_account_flows)
for table in sorted(_FLOW_TABLE_NAMES):
    cls_name = MODEL_BY_TABLE[table].__name__
    check("collect_account_flows 里查了 %s（%s）" % (table, cls_name),
          cls_name in src_code,
          "源码里找不到 %s —— 可能登记了注册表却忘了写取数逻辑" % cls_name)

check("collect_account_flows 明确指向注册表（免得后人不知道要同步两处）",
      "FLOW_SOURCES" in src_code, "函数注释里没提 FLOW_SOURCES")


# ===========================================================================
section("[4] 功能性抽查：实际产生的 kind 都声明过，常见 kind 确实在跑")
db = SessionLocal()
try:
    init_db(db)
    # ⚠️ 必须显式 seed_demo：写演示数据的是 lifespan，init_db 本身不写
    seed_demo(db)
    observed = set()
    from app.models import Account

    for acc in db.query(Account).filter(Account.user_id == 1).all():
        for row in collect_account_flows(db, acc.id, 1):
            observed.add(row["kind"])
finally:
    db.close()

declared_kinds = {s["kind"] for s in FLOW_SOURCES}
check("演示数据确实产生了几类流水（说明口径在跑）", len(observed) >= 3,
      "只观察到 %s" % sorted(observed))
check("🔴 实际产生的 kind 全部已声明（没有口径漂移）",
      observed <= declared_kinds,
      "未声明的 kind：%s（声明的是 %s）" % (sorted(observed - declared_kinds),
                                    sorted(declared_kinds)))
for k in ("收支", "存取", "转账"):
    check("演示数据覆盖到「%s」" % k, k in observed, "未观察到，演示数据可能变了")

print()
print("=" * 68)
if _fails:
    print("结果：%d/%d 通过，%d 失败" % (_checks - len(_fails), _checks, len(_fails)))
    for x in _fails:
        print("  - %s" % x)
    sys.exit(1)
print("结果：全部 %d 项检查通过 ✅" % _checks)
