# -*- coding: utf-8 -*-
"""运行时健康快照：把「账平不平」暴露到 /api/health，带缓存。

## 为什么需要它

`test_balance_audit.py` 的 61 项断言守住了资金守恒，但它们只在**改代码时**跑
（本地或 CI 门禁）。部署之后账有没有平，没人看 —— 而手工改过余额、漏记一笔、
导入了一份不完整的备份，都会让账悄悄不平。

所以把对账结果暴露到 `/api/health`：部署后一条 `curl` 就能看到。

## 关键约束：绝不能让状态码依赖业务数据

`/api/health` 的消费者有：
  · `Dockerfile` / `docker-compose.yml` / `docker-compose.local.yml` 的 **HEALTHCHECK**
  · `Login.jsx`（登录页显示版本）
  · `Settings.jsx`（设置页显示版本）

如果让它在账不平时返回非 2xx，后果是「只是财务差异 → 容器被标 unhealthy、
自查命令失败、登录页报错」—— 一个数据问题被误报成服务故障。
因此本模块**只提供字段**，HTTP 状态码永远由调用方保持 200。

## 为什么必须缓存

HEALTHCHECK 每 30 秒打一次，而全量对账是 9 个来源 × N 个账户的查询。
实时算会让健康检查变成重负载。策略：
  · 启动时算一次（并用日志留痕）
  · 后台线程按 TTL（默认 10 分钟）刷新
  · `/health` **只读缓存**；缓存为空时才现算一次
"""
from datetime import datetime, timedelta

from . import backup
from . import schema_meta
from .utils import reconcile_summary

TTL = timedelta(minutes=10)

_cache = {"at": None, "data": None}


def _now():
    return datetime.now()


def refresh_reconcile(db, force: bool = False) -> dict:
    """（重新）计算对账摘要并写入缓存。force=False 且未过期时直接返回缓存。"""
    if not force and _cache["data"] is not None and _cache["at"] is not None:
        if _now() - _cache["at"] < TTL:
            return _cache["data"]
    data = reconcile_summary(db)
    data["checked_at"] = _now().isoformat(timespec="seconds")
    _cache["at"] = _now()
    _cache["data"] = data
    return data


def reconcile_fields(db) -> dict:
    """/api/health 用：只读缓存（缓存为空时现算一次）。不抛异常。"""
    try:
        data = _cache["data"]
        if data is None:
            data = refresh_reconcile(db, force=True)
    except Exception as exc:  # noqa: BLE001 —— 健康接口本身绝不能把服务拖垮
        return {
            "books_balanced": None,
            "reconcile": {"error": "%s: %s" % (type(exc).__name__, exc)},
        }
    return {
        "books_balanced": data.get("balanced"),
        "reconcile": {
            "checked_at": data.get("checked_at"),
            "users": data.get("users"),
            "accounts": data.get("accounts"),
            "unbalanced": data.get("unbalanced"),
            "worst": data.get("worst"),
            "cached_ttl_seconds": int(TTL.total_seconds()),
        },
    }


def log_startup(db):
    """启动自检：把对账结果写进日志（这是「部署后就知道账平不平」的第一道提示）。"""
    try:
        data = refresh_reconcile(db, force=True)
    except Exception as exc:  # noqa: BLE001
        print("[health] 启动对账自检失败：%s: %s" % (type(exc).__name__, exc))
        return
    if data.get("balanced"):
        print("[health] 启动对账自检：全部 %d 个账户「期初基准 + 全部资金流水 = 实际余额」 ✅"
              % data.get("accounts", 0))
    else:
        worst = data.get("worst") or {}
        print("[health][WARN] 启动对账自检：%d/%d 个账户不平，最大差异 %s 元（%s · %s）"
              % (data.get("unbalanced", 0), data.get("accounts", 0),
                 worst.get("diff"), worst.get("user"), worst.get("account")))
        print("[health][WARN] 这不是服务故障，是账目差异。可在 App「财富总览 → 余额对账」查看明细。")


def maintenance_loop():
    """后台线程：按 TTL 刷新对账缓存（让 /health 永远只读缓存、永远快）。"""
    import time

    from .database import SessionLocal

    while True:
        try:
            db = SessionLocal()
            try:
                refresh_reconcile(db)
            finally:
                db.close()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(max(60, int(TTL.total_seconds() / 5)))


def startup(db):
    """启动时统一跑一遍：对账自检 + 备份检查。"""
    log_startup(db)
    backup.log_startup()
    schema_meta.log_startup(db)


def fields(db) -> dict:
    """/api/health 里挂的健康字段（全量）。所有子项都各自兜异常。"""
    out = {}
    out.update(schema_meta.health_fields())
    out.update(reconcile_fields(db))
    out.update(backup.health_fields())
    return out
