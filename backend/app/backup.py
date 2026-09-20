# -*- coding: utf-8 -*-
"""自动备份：每日把全账号数据导出成 JSON，轮转保留最近 N 份。

## 为什么自用场景特别需要它

这个应用是**单用户、自托管**的：`./data` 里的 SQLite 是家里这本账的**唯一副本**，
而且**没有第二个人会发现问题**。卷损坏、误删目录、一次坏升级 —— 任何一条都是全损，
可能几周后才察觉。现有的只有「设置页手动导出」，取决于你记不记得点。

## 设计要点

- **目录可指向异卷**：默认 `./data/backups`，但这和数据库同卷 —— 卷坏了备份一起没。
  用 `BACKUP_DIR` 指到 NAS 上另一处共享目录，才算真正多一份保险。
- **每日一份**：按日期判重，不是每次启动都写（否则重启几次就把轮转挤满）。
- **启动校验最近一份**：能解析、含 `users`、每份含 `version` 与必要的表键，
  否则在 `/health` 里报出来。
- **只读不还原**：本模块不提供自动还原。还原是危险动作（覆盖当前账号全部数据），
  必须由人在「设置管理 → 数据管理 → 导入恢复」里手动做。
"""
import glob
import json
import os
import threading
import time
from datetime import datetime

from .export_data import BUSINESS_TABLES, build_export

DEFAULT_KEEP = 14
_FILE_PREFIX = "fw-backup-"

_status = {
    "enabled": None,
    "dir": None,
    "keep": None,
    "count": 0,
    "latest": None,
    "latest_at": None,
    "ok": None,
    "message": "尚未检查",
    "same_volume_warning": False,
}


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
def data_dir() -> str:
    return os.environ.get("DATA_DIR", "/data")


def backup_dir() -> str:
    d = (os.environ.get("BACKUP_DIR") or "").strip()
    return d or os.path.join(data_dir(), "backups")


def keep_count() -> int:
    try:
        return max(1, int(os.environ.get("BACKUP_KEEP", DEFAULT_KEEP)))
    except (TypeError, ValueError):
        return DEFAULT_KEEP


def enabled() -> bool:
    return os.environ.get("BACKUP_ENABLED", "true").lower() not in ("0", "false", "no")


# ---------------------------------------------------------------------------
# 写与轮转
# ---------------------------------------------------------------------------
def _stamp(dt=None) -> str:
    # 带微秒：同一秒内连点两次「立即备份」也不会重名（重名会覆盖，还会让轮转算错）
    return (dt or datetime.now()).strftime("%Y%m%d-%H%M%S-%f")


def run_backup(db, reason: str = "scheduled") -> dict:
    """导出全部账号到一个备份文件（含元信息），随后轮转。返回结果摘要。"""
    from .main import VERSION
    from .models import User
    from .schema_meta import CODE_SCHEMA_VERSION

    target_dir = backup_dir()
    os.makedirs(target_dir, exist_ok=True)

    users = db.query(User).order_by(User.id).all()
    payload = {
        "_backup": {
            "file_version": 1,
            "app_version": VERSION,
            "schema_version": CODE_SCHEMA_VERSION,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "reason": reason,
            "users": [u.username for u in users],
        },
        # 每个账号一份完整导出（形状与「设置管理 → 导出备份」完全一致，
        # 因此这份文件里的任一账号数据可以直接拿去「导入恢复」）
        "users": {u.username: build_export(db, u) for u in users},
    }

    name = "%s%s.json" % (_FILE_PREFIX, _stamp())
    path = os.path.join(target_dir, name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)  # 原子替换：避免读到写了一半的备份

    removed = rotate()
    removed_paths = [os.path.basename(p) for p in removed]
    size = os.path.getsize(path)
    print("[backup] 已写出 %s（%.1f KB，%d 个账号）%s"
          % (name, size / 1024.0, len(users),
             "，轮转删除 %d 份" % len(removed) if removed else ""))
    verify_latest()
    return {"file": name, "path": path, "size": size,
            "users": [u.username for u in users], "removed": removed_paths}


def list_files() -> list[str]:
    return sorted(glob.glob(os.path.join(backup_dir(), _FILE_PREFIX + "*.json")))


def rotate(keep: int | None = None) -> list[str]:
    """只保留最新 keep 份（文件名带时间戳，字典序即时间序）。返回被删路径。"""
    keep = keep or keep_count()
    files = list_files()
    if len(files) <= keep:
        return []
    removed = []
    for path in files[: len(files) - keep]:
        try:
            os.remove(path)
            removed.append(path)
        except OSError:
            pass
    return removed


def has_today() -> bool:
    today = datetime.now().strftime("%Y%m%d")
    return any(today in os.path.basename(p) for p in list_files())


def maybe_backup(db) -> dict | None:
    """每日一份：今天已有就跳过。返回备份摘要或 None。"""
    if not enabled():
        return None
    if has_today():
        return None
    return run_backup(db, reason="scheduled")


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------
def verify_file(path: str) -> tuple[bool, str]:
    """校验一份备份是否可用：能解析、结构对、账号导出里含必要键。"""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:  # noqa: BLE001
        return False, "无法解析：%s: %s" % (type(exc).__name__, exc)

    if not isinstance(data, dict) or "users" not in data or not isinstance(data["users"], dict):
        return False, "缺少 users 段（不是本应用的备份文件？）"
    if not data["users"]:
        return False, "备份里没有任何账号数据"

    for name, exp in data["users"].items():
        if not isinstance(exp, dict):
            return False, "账号 %s 的导出不是对象" % name
        if exp.get("version") is None:
            return False, "账号 %s 的导出缺少 version 字段" % name
        missing = [t for t in ("accounts", "transactions") if t not in exp]
        if missing:
            return False, "账号 %s 的导出缺少表：%s" % (name, "、".join(missing))
    return True, ""


def verify_latest() -> dict:
    """校验最新一份备份并更新状态。"""
    _status["enabled"] = enabled()
    _status["dir"] = backup_dir()
    _status["keep"] = keep_count()
    _status["same_volume_warning"] = _is_same_volume()

    files = list_files()
    _status["count"] = len(files)
    if not files:
        _status["latest"] = None
        _status["latest_at"] = None
        _status["ok"] = False if enabled() else None
        _status["message"] = ("尚未产生任何备份（等首次定时备份，或点「立即备份」）"
                              if enabled() else "自动备份已关闭（BACKUP_ENABLED=false）")
        return dict(_status)

    latest = files[-1]
    ok, why = verify_file(latest)
    _status["latest"] = os.path.basename(latest)
    try:
        _status["latest_at"] = datetime.fromtimestamp(os.path.getmtime(latest)).isoformat(timespec="seconds")
    except OSError:
        _status["latest_at"] = None
    _status["ok"] = ok
    _status["message"] = "最近备份可用" if ok else "最近备份有问题：%s" % why
    return dict(_status)


def _is_same_volume() -> bool:
    """备份目录是否与数据目录同卷（同卷意味着卷损坏时备份一起没）。"""
    try:
        data = os.path.abspath(data_dir())
        bk = os.path.abspath(backup_dir())
        # 用最近存在的祖先目录的盘符/设备号近似判断
        a, b = data, bk
        while a and not os.path.exists(a):
            a = os.path.dirname(a)
        while b and not os.path.exists(b):
            b = os.path.dirname(b)
        return os.path.splitdrive(a)[0] == os.path.splitdrive(b)[0] and bk.startswith(data)
    except Exception:  # noqa: BLE001
        return False


def log_startup():
    st = verify_latest()
    if not st["enabled"]:
        print("[backup] 自动备份已关闭（BACKUP_ENABLED=false）")
        return
    print("[backup] 目录 %s（保留最近 %d 份，当前 %d 份）" % (st["dir"], st["keep"], st["count"]))
    if st["ok"]:
        print("[backup] 最近备份 %s @ %s ✅" % (st["latest"], st["latest_at"]))
    else:
        print("[backup][WARN] %s" % st["message"])
    if st["same_volume_warning"]:
        print("[backup][WARN] 备份目录与数据库同在 ./data 下 —— 卷损坏时两者一起没。"
              "建议把 BACKUP_DIR 指向 NAS 上另一处目录。")


def health_fields() -> dict:
    st = _status if _status["dir"] is not None else verify_latest()
    return {
        "backup_enabled": st["enabled"],
        "backup_ok": st["ok"],
        "backup_count": st["count"],
        "backup_latest_at": st["latest_at"],
        "backup_dir": st["dir"],
        "backup_same_volume": st["same_volume_warning"],
        "backup_message": st["message"],
    }


def status() -> dict:
    return dict(_status if _status["dir"] is not None else verify_latest())


# ---------------------------------------------------------------------------
# 后台线程
# ---------------------------------------------------------------------------
def _loop():
    from .database import SessionLocal

    while True:
        try:
            if enabled():
                db = SessionLocal()
                try:
                    maybe_backup(db)
                finally:
                    db.close()
            verify_latest()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(3600)  # 每小时看一次「今天有没有备份」，足够及时


def start_scheduler():
    t = threading.Thread(target=_loop, name="auto-backup", daemon=True)
    t.start()
