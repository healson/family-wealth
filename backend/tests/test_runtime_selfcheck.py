# -*- coding: utf-8 -*-
"""运行时自检回归测试（v1.9.0）

覆盖三件事：

  1. **schema 版本哨兵** —— 防止「旧镜像 + 新数据库」静默算错。
     本项目的迁移只解决「新镜像 + 旧库」，反方向原本无人管：旧代码写入时不会维护
     新增的账户快照列，新代码再读到时走父记录兜底 → **静默错误归属**，不报错。

  2. **把对账暴露到运行时** —— 61 项守恒断言只在改代码时跑，部署之后账平不平没人看。
     现在 `/api/health` 带 `books_balanced`，启动时也会写日志。
     ⚠️ 关键约束：`/api/health` 被三处 Docker HEALTHCHECK + 登录页 + 设置页消费，
        所以**状态码必须恒为 200** —— 账不平是业务状态，不能把容器标成 unhealthy。
        本测试专门守这一条。

  3. **删除归档 + 自动备份** —— 自用场景没有第二个人兜底，所以「能找回」与「有备份」
     的优先级高于架构美化。归档表**只写不读**，因此必须证明它没污染资金守恒。

最后一个 section 用真实数据验证「删了东西之后，余额对账仍全为 0」。
"""
import glob
import json
import os
import shutil
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="fw_selfcheck_")
os.makedirs(os.path.join(TMP, "static", "assets"), exist_ok=True)
os.environ["DATA_DIR"] = TMP
os.environ["STATIC_DIR"] = os.path.join(TMP, "static")
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["TZ"] = "Asia/Shanghai"
os.environ["BACKUP_DIR"] = os.path.join(TMP, "backups")
os.environ.pop("BACKUP_ENABLED", None)

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import backup as backup_mod  # noqa: E402
from app import health as health_mod  # noqa: E402
from app import schema_meta  # noqa: E402
from app import seed as seed_mod  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import VERSION, app  # noqa: E402
from app.models import Account, DeletedRecord  # noqa: E402
from app.utils import reconcile_accounts  # noqa: E402

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


def fresh_db():
    """开一个会话；调用方负责 close（与其它检查脚本保持一致的写法）。"""
    return SessionLocal()


def account_diffs(user_id=1):
    db = fresh_db()
    try:
        return {r["name"]: r["diff"] for r in reconcile_accounts(db, user_id)}
    finally:
        db.close()


def first_account_id(user_id=1) -> int:
    db = fresh_db()
    try:
        return db.query(Account).filter(Account.user_id == user_id).first().id
    finally:
        db.close()


# ===========================================================================
# 用 `with TestClient(app)` 让 lifespan 真正跑起来（否则启动自检不会执行）
# ===========================================================================
with TestClient(app) as client:
    _login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert _login.status_code == 200, _login.text
    H = {"Authorization": "Bearer %s" % _login.json()["token"]}

    # -----------------------------------------------------------------------
    section("[1] 启动自检（lifespan 跑了吗）")
    check("schema 状态已判定（不是 unknown）",
          schema_meta.STARTUP_STATUS["status"] not in ("unknown",),
          str(schema_meta.STARTUP_STATUS["status"]))
    check("全新库首次启动 → status in (ok, upgraded)",
          schema_meta.STARTUP_STATUS["status"] in ("ok", "upgraded"),
          str(schema_meta.STARTUP_STATUS["status"]))
    check("schema 版本已写入库内（下次启动能读到）",
          schema_meta.read_db_version(engine) == schema_meta.CODE_SCHEMA_VERSION,
          "库内=%r" % schema_meta.read_db_version(engine))
    check("没有缺失的声明列", not schema_meta.STARTUP_STATUS["missing_columns"],
          str(schema_meta.STARTUP_STATUS["missing_columns"]))
    check("对账缓存已由启动自检填上",
          health_mod._cache["data"] is not None, "启动没跑对账")

    # -----------------------------------------------------------------------
    section("[2] /api/health 契约（不需要登录）")
    r = client.get("/api/health")
    check("GET /api/health -> 200（无鉴权可访问）", r.status_code == 200, str(r.status_code))
    h = r.json()
    check("含 version 且等于 VERSION", h.get("version") == VERSION, str(h.get("version")))
    check("含 status=ok", h.get("status") == "ok", str(h.get("status")))
    check("含 books_balanced 且是 bool", isinstance(h.get("books_balanced"), bool),
          repr(h.get("books_balanced")))
    check("含 schema_ok 且是 bool", isinstance(h.get("schema_ok"), bool), repr(h.get("schema_ok")))
    check("含 schema_code_version", h.get("schema_code_version") == schema_meta.CODE_SCHEMA_VERSION,
          str(h.get("schema_code_version")))
    check("含 backup_ok / backup_count / backup_dir",
          "backup_ok" in h and "backup_count" in h and "backup_dir" in h, str(sorted(h)))
    check("reconcile 里带 checked_at（说明是缓存快照）",
          bool((h.get("reconcile") or {}).get("checked_at")), str(h.get("reconcile")))
    blob = json.dumps(h, ensure_ascii=False)
    check("health 响应不含任何凭据字段",
          not any(k in blob for k in ("PASSWORD", "SECRET", "ghp_", "TOKEN")), blob[:200])

    section("[2b] 全新演示数据的账本应当是平的")
    check("books_balanced is True", h.get("books_balanced") is True,
          "差异：%s" % json.dumps((h.get("reconcile") or {}).get("worst"), ensure_ascii=False))
    check("全部账户对账差异为 0", all(v == 0 for v in account_diffs().values()),
          str(account_diffs()))

    # -----------------------------------------------------------------------
    section("[3] 🔴 账不平时 /api/health 仍必须 200（关键回归守卫）")
    db = fresh_db()
    victim = db.query(Account).filter(Account.user_id == 1).first()
    victim_id, victim_name, original = victim.id, victim.name, float(victim.balance)
    victim.balance = original + 123.45  # 手工制造一笔对不上的差异
    db.commit()
    db.close()

    rr = client.post("/api/system/health-refresh", headers=H)
    check("POST /api/system/health-refresh -> 200", rr.status_code == 200, rr.text[:200])
    check("强制刷新后 update 判定为「不平」", rr.json()["reconcile"]["balanced"] is False,
          str(rr.json()["reconcile"]))

    r2 = client.get("/api/health")
    check("账不平时 /api/health 仍然是 200", r2.status_code == 200, str(r2.status_code))
    check("且 books_balanced 变成 False", r2.json().get("books_balanced") is False,
          repr(r2.json().get("books_balanced")))
    check("worst 指到了出问题的账户",
          (r2.json().get("reconcile") or {}).get("worst", {}).get("account") == victim_name,
          str((r2.json().get("reconcile") or {}).get("worst")))
    check("schema_ok 不受账目问题影响（两个信号互相独立）",
          r2.json().get("schema_ok") is True, repr(r2.json().get("schema_ok")))

    # 复原
    db = fresh_db()
    a = db.get(Account, victim_id)
    a.balance = original
    db.commit()
    db.close()
    client.post("/api/system/health-refresh", headers=H)
    check("复原后 books_balanced 回到 True",
          client.get("/api/health").json().get("books_balanced") is True, "未复原")

    # -----------------------------------------------------------------------
    section("[4] 删除归档：删了能找回，且不污染资金守恒")
    acc_id = first_account_id()

    before_diffs = account_diffs()
    mk = client.post("/api/transactions", headers=H, json={
        "type": "支出", "amount": 66.66, "date": "2026-09-19",
        "account_id": acc_id, "note": "归档回归测试",
    })
    check("POST /api/transactions -> 200", mk.status_code == 200, mk.text[:200])
    txn_id = mk.json()["id"]

    db = fresh_db()
    n_before = db.query(DeletedRecord).count()
    db.close()

    dl = client.delete("/api/transactions/%d" % txn_id, headers=H)
    check("DELETE /api/transactions/{id} -> 200", dl.status_code == 200, dl.text[:200])

    db = fresh_db()
    rec = db.query(DeletedRecord).filter(DeletedRecord.module == "transactions",
                                         DeletedRecord.record_id == txn_id).first()
    n_after = db.query(DeletedRecord).count()
    db.close()
    check("归档表新增了一条", n_after == n_before + 1, "%d -> %d" % (n_before, n_after))
    check("归档记录的 module / record_id 正确",
          rec is not None and rec.module == "transactions" and rec.record_id == txn_id,
          str((rec and rec.module, rec and rec.record_id)))
    if rec is not None:
        payload = json.loads(rec.payload)
        check("归档 payload 保留了原记录的全部字段（含金额与账户）",
              float(payload.get("amount")) == 66.66 and payload.get("account_id") == acc_id,
              json.dumps({k: payload.get(k) for k in ("amount", "account_id", "type")},
                         ensure_ascii=False))
        check("归档 label 是人能看懂的摘要", bool(rec.label), repr(rec.label))

    lst = client.get("/api/data/deleted", headers=H)
    check("GET /api/data/deleted -> 200", lst.status_code == 200, lst.text[:200])
    body = lst.json()
    check("列表里能找到这条归档", any(i["record_id"] == txn_id and i["module"] == "transactions"
                                       for i in body["items"]), str(body.get("total")))
    check("列表返回分组统计", any(m["module"] == "transactions" for m in body["modules"]),
          str(body.get("modules")))
    exp = client.get("/api/data/deleted/export", headers=H)
    check("GET /api/data/deleted/export -> 200", exp.status_code == 200, exp.text[:200])
    check("导出里含 items 且带说明（避免被误当账目数据）",
          isinstance(exp.json().get("items"), list) and "不是账目数据" in exp.json().get("note", ""),
          str(exp.json().get("note"))[:120])

    after_diffs = account_diffs()
    check("🔴 删除后余额对账差异仍全为 0（归档未污染资金守恒）",
          all(v == 0 for v in after_diffs.values()), str(after_diffs))
    check("删除前后对账结果一致", before_diffs.keys() == after_diffs.keys(),
          "%s vs %s" % (sorted(before_diffs), sorted(after_diffs)))

    # -----------------------------------------------------------------------
    section("[5] 自动备份：产出、校验、轮转")
    bn = client.post("/api/data/backup/now", headers=H)
    check("POST /api/data/backup/now -> 200", bn.status_code == 200, bn.text[:250])
    files = backup_mod.list_files()
    check("备份目录里出现了文件", len(files) >= 1, str(files))
    ok, why = backup_mod.verify_file(files[-1]) if files else (False, "无文件")
    check("最新一份备份可解析且结构正确", ok, why)
    with open(files[-1], encoding="utf-8") as fh:
        bk = json.load(fh)
    check("备份含 _backup 元信息（app_version / schema_version）",
          "_backup" in bk and "app_version" in bk["_backup"] and "schema_version" in bk["_backup"],
          str(bk.get("_backup")))
    check("备份覆盖了 admin 账号的数据",
          "admin" in bk.get("users", {}) and "accounts" in bk["users"]["admin"],
          str(list(bk.get("users", {}).keys())))

    st = client.get("/api/data/backup/status", headers=H)
    check("GET /api/data/backup/status -> 200", st.status_code == 200, st.text[:200])
    check("status.ok 为 True", st.json().get("ok") is True, str(st.json()))
    fl = client.get("/api/data/backup/files", headers=H)
    check("GET /api/data/backup/files 能列出文件", fl.status_code == 200 and fl.json()["files"],
          fl.text[:200])

    # 轮转：只保留 2 份
    os.environ["BACKUP_KEEP"] = "2"
    for _ in range(3):
        backup_mod.run_backup(fresh_db(), reason="rotation-test")
    kept = backup_mod.list_files()
    check("轮转后只剩 BACKUP_KEEP=2 份", len(kept) == 2, "实际 %d 份" % len(kept))
    os.environ.pop("BACKUP_KEEP", None)

    # 损坏最新一份 → backup_ok False，但 /health 仍 200
    with open(kept[-1], "w", encoding="utf-8") as fh:
        fh.write("{ 这不是 JSON")
    backup_mod.verify_latest()
    check("备份损坏时 status.ok 变 False",
          client.get("/api/data/backup/status", headers=H).json().get("ok") is False,
          "未检测到损坏")
    r3 = client.get("/api/health")
    check("🔴 备份损坏时 /api/health 仍然 200", r3.status_code == 200, str(r3.status_code))
    check("且 backup_ok 变成 False", r3.json().get("backup_ok") is False,
          repr(r3.json().get("backup_ok")))
    check("books_balanced 不受备份问题影响", r3.json().get("books_balanced") is True, "被影响")

    # -----------------------------------------------------------------------
    section("[6] 自动备份文件可直接拿去「导入恢复」")
    good = [f for f in backup_mod.list_files()]
    # 用较早那份（未被损坏的）当输入
    src = good[0] if len(good) > 1 else good[-1]
    with open(src, encoding="utf-8") as fh:
        payload = json.load(fh)
    bad = client.post("/api/data/import", headers=H,
                      json={"data": {"_backup": {}, "users": {"某个不存在的账号": {}}}})
    check("备份文件里没有当前账号时报 400 且说清楚",
          bad.status_code == 400 and "没有账号" in bad.json().get("detail", ""),
          bad.text[:200])
    good_req = client.post("/api/data/import", headers=H, json={"data": payload})
    check("把备份文件原样喂给导入接口 -> 200（形状兼容）",
          good_req.status_code == 200, good_req.text[:250])
    client.post("/api/system/health-refresh", headers=H)
    check("导入后账仍然平（导入不会破坏守恒）",
          all(v == 0 for v in account_diffs().values()), str(account_diffs()))
    # ⚠️ 导入是「清空后重建」，账户 id 全部换新 —— 后面用到 acc_id 的地方必须重新取
    acc_id = first_account_id()

    # -----------------------------------------------------------------------
    section("[7] schema 哨兵：库比代码新 → 警告但不拒绝启动")
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO _meta(key, value) VALUES('schema_version', '999') "
            "ON CONFLICT(key) DO UPDATE SET value = '999'"))

    db = fresh_db()
    try:
        seed_mod.init_db(db)  # 迁移 + 哨兵判定 + 写回当前版本
    finally:
        db.close()

    st2 = schema_meta.STARTUP_STATUS
    check("识别为 newer_db", st2["status"] == "newer_db", str(st2))
    check("记录了库内版本 999", st2["db_version"] == 999, str(st2["db_version"]))
    check("message 明确提示这是旧镜像", "旧的" in st2["message"], st2["message"][:160])
    check("message 给出可操作建议（换回新版镜像 / 先导出备份）",
          "镜像" in st2["message"] and "备份" in st2["message"], st2["message"][:200])
    r4 = client.get("/api/health")
    check("🔴 库比代码新时应用照常服务（不拒绝启动）",
          r4.status_code == 200, str(r4.status_code))
    check("但 schema_ok 报 False", r4.json().get("schema_ok") is False,
          repr(r4.json().get("schema_ok")))
    check("schema_message 透传到 health",
          "旧的" in (r4.json().get("schema_message") or ""),
          str(r4.json().get("schema_message"))[:120])
    check("迁移后库内版本被写回当前版本（避免下次重复告警）",
          schema_meta.read_db_version(engine) == schema_meta.CODE_SCHEMA_VERSION,
          str(schema_meta.read_db_version(engine)))
    check("库比代码新时数据仍可正常读写（GET /api/accounts 200）",
          client.get("/api/accounts", headers=H).status_code == 200, "读失败")
    check("库比代码新时写入也正常（POST /api/transactions 200）",
          client.post("/api/transactions", headers=H, json={
              "type": "支出", "amount": 1.0, "date": "2026-09-19",
              "account_id": acc_id, "note": "哨兵测试"}).status_code == 200, "写失败")

shutil.rmtree(TMP, ignore_errors=True)

print()
print("=" * 68)
if _fails:
    print("结果：%d/%d 通过，%d 失败" % (_checks - len(_fails), _checks, len(_fails)))
    for x in _fails:
        print("  - %s" % x)
    sys.exit(1)
print("结果：全部 %d 项检查通过 ✅" % _checks)
