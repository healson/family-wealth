# -*- coding: utf-8 -*-
"""schema 版本哨兵：防止「旧镜像 + 新数据库」静默跑出错误数据。

## 为什么需要

本项目的迁移是**单向的**：启动时在 `seed.py::init_db` 里跑幂等 `ALTER TABLE ADD COLUMN`
补齐缺失列。这解决了「新镜像 + 旧库」，但**「旧镜像 + 新库」没有任何保护**。

而这个方向的失败方式很隐蔽，不是崩，而是**悄悄算错**：

    新版本给 `policy_payments` 加了 `account_id`（缴费账户快照），
    并迁移时按父记录回填了历史数据。
    → 你把镜像回滚到旧版本（新版本有问题时很自然）
    → 旧代码创建新缴费记录时**不写 account_id**（它的模型里没这列）
    → 新代码再读到时，`p.account_id or p.policy.account_id` 走兜底分支
    → 若这期间改过保单的缴费账户，这笔缴费就被归属到**错误的账户**
    → 余额对账失衡，且没有任何报错

所以需要一个显式标记：库里的 schema 版本 > 代码认识的版本时，大声警告。

## 设计取舍：警告，不拒绝启动

自托管家庭应用的可用性优先于严格性 —— 如果这里写 `raise`，一旦哨兵本身有 bug，
用户会面对「应用起不来、而且改不动自己的账」的绝境，那比数据风险更糟。
因此策略是：**醒目警告 + 暴露在 /api/health + 前端横幅**，把判断权交回用户。

## 用法

- 每次改结构（加列/加表/改类型）→ 把 `CODE_SCHEMA_VERSION` +1。
- `init_db` 里：迁移前读库内版本做比对，迁移后写入当前版本。
- 结果存进 `STARTUP_STATUS`，由 `/api/health` 与 `/api/system/info` 输出。
"""
import os
from datetime import datetime

from sqlalchemy import text

# ⚠️ 每次改表结构（加列 / 加表 / 改列类型）都 +1，并同步在 README 版本历史里说明。
#   1 = v1.7.7 及以前的强关联快照列时代
#   2 = v1.9.0（新增 deleted_records 回收站表）
CODE_SCHEMA_VERSION = 2

_META_DDL = "CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT)"

# 启动时填充，供 /api/health 读取。进程内单例，不落库。
STARTUP_STATUS = {
    "code_version": CODE_SCHEMA_VERSION,
    "db_version": None,
    "status": "unknown",      # ok / upgraded / newer_db / unknown
    "missing_columns": [],
    "checked_at": None,
    "message": "",
}


def _now():
    return datetime.now().isoformat(timespec="seconds")


def read_db_version(engine) -> int | None:
    """读库内记录的 schema 版本；表不存在或没记录返回 None。"""
    try:
        with engine.connect() as conn:
            conn.execute(text(_META_DDL))
            conn.commit()
            row = conn.execute(
                text("SELECT value FROM _meta WHERE key = 'schema_version'")
            ).fetchone()
        return int(row[0]) if row and row[0] is not None else None
    except Exception:  # noqa: BLE001 —— 哨兵绝不能因为自身异常影响启动
        return None


def write_db_version(engine, version: int | None = None):
    v = CODE_SCHEMA_VERSION if version is None else version
    try:
        with engine.begin() as conn:
            conn.execute(text(_META_DDL))
            conn.execute(
                text("INSERT INTO _meta(key, value) VALUES('schema_version', :v) "
                     "ON CONFLICT(key) DO UPDATE SET value = :v"),
                {"v": str(v)},
            )
    except Exception:  # noqa: BLE001
        pass


def missing_columns(engine, declared) -> list[str]:
    """校验声明的资金快照列是否真的都在库里。

    这是对「迁移静默失败」的兜底：`ensure_strong_link_columns` 若因为某个异常没跑完，
    启动不会崩，但以后读这些列会 OperationalError。这里主动查一遍，把缺失的列报出来。

    declared: [(table, column), ...]
    """
    from sqlalchemy import inspect

    missing = []
    try:
        insp = inspect(engine)
        tables = set(insp.get_table_names())
        cache: dict[str, set[str]] = {}
        for table, col in declared:
            if table not in tables:
                missing.append("%s.%s（表不存在）" % (table, col))
                continue
            if table not in cache:
                cache[table] = {c["name"] for c in insp.get_columns(table)}
            if col not in cache[table]:
                missing.append("%s.%s" % (table, col))
    except Exception:  # noqa: BLE001
        return []
    return missing


def check_and_record(engine, db_version_before: int | None, declared_columns=()) -> dict:
    """在迁移之后调用：判定状态并写入 STARTUP_STATUS，返回该 dict。"""
    missing = missing_columns(engine, declared_columns)
    STARTUP_STATUS["code_version"] = CODE_SCHEMA_VERSION
    STARTUP_STATUS["db_version"] = db_version_before
    STARTUP_STATUS["missing_columns"] = missing
    STARTUP_STATUS["checked_at"] = _now()

    if missing:
        STARTUP_STATUS["status"] = "missing_columns"
        STARTUP_STATUS["message"] = (
            "库中缺少本次代码声明的列：%s\n"
            "这通常意味着迁移未跑完。请检查启动日志；数据未被破坏，"
            "但读这些列的功能会报错。" % "、".join(missing)
        )
    elif db_version_before is None:
        STARTUP_STATUS["status"] = "ok"
        STARTUP_STATUS["message"] = "首次记录 schema 版本（v%d）。" % CODE_SCHEMA_VERSION
    elif db_version_before > CODE_SCHEMA_VERSION:
        STARTUP_STATUS["status"] = "newer_db"
        STARTUP_STATUS["message"] = (
            "⚠️ 数据库 schema 版本（v%d）**高于**当前镜像认识的版本（v%d），"
            "说明这个镜像是**旧的**。多余列不会让程序崩，但旧代码写入时不会维护"
            "新增的账户快照列，之后再换回新版可能把资金归属到错误账户（静默失衡）。\n"
            "建议：换回 v%d 或更新的镜像；若确实要用旧版，请先导出备份，"
            "并避免变动保单缴费账户 / 投资关联现金账户。"
            % (db_version_before, CODE_SCHEMA_VERSION, db_version_before)
        )
    elif db_version_before < CODE_SCHEMA_VERSION:
        STARTUP_STATUS["status"] = "upgraded"
        STARTUP_STATUS["message"] = "已从 schema v%d 迁移到 v%d。" % (
            db_version_before, CODE_SCHEMA_VERSION)
    else:
        STARTUP_STATUS["status"] = "ok"
        STARTUP_STATUS["message"] = "schema 版本一致（v%d）。" % CODE_SCHEMA_VERSION

    return STARTUP_STATUS


def health_fields() -> dict:
    """给 /api/health 用的精简字段。"""
    st = STARTUP_STATUS["status"]
    return {
        "schema_code_version": STARTUP_STATUS["code_version"],
        "schema_db_version": STARTUP_STATUS["db_version"],
        "schema_status": st,
        "schema_ok": st in ("ok", "upgraded"),
        "schema_message": STARTUP_STATUS["message"],
    }


def log_startup(db=None):
    st = STARTUP_STATUS
    tag = {
        "ok": "[schema]",
        "upgraded": "[schema]",
        "newer_db": "[schema][WARN]",
        "missing_columns": "[schema][ERROR]",
        "unknown": "[schema]",
    }.get(st["status"], "[schema]")
    print("%s %s" % (tag, st["message"]))
    if st["status"] in ("newer_db", "missing_columns"):
        print("%s 应用继续启动（自托管场景可用性优先），但请尽快处理。" % tag)


def data_dir():
    return os.environ.get("DATA_DIR", "/data")
