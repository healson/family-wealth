# -*- coding: utf-8 -*-
"""数据导出/导入（JSON 全量备份与恢复，按账号隔离）+ 回收站 + 手动备份触发。

导出的字段形状由 `app/export_data.py` 唯一实现（自动备份也用它），本模块只负责
HTTP 接口与导入时的外键重建。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import backup
from ..auth import delete_user_data, get_current_user
from ..database import get_db
from ..export_data import (
    CHILD_MODELS,
    EXPORT_VERSION,
    PARENT_MODELS,
    build_export,
    convert_cols,
)
from ..models import (
    Attachment,
    DeletedRecord,
    ReminderRule,
    User,
)

router = APIRouter(
    prefix="/api/data",
    tags=["数据导入导出"],
    dependencies=[Depends(get_current_user)],
)


# ---------------------------------------------------------------------------
# 导出 / 导入
# ---------------------------------------------------------------------------
@router.get("/export")
def export_data(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """导出当前账号全量数据为 JSON 备份"""
    return build_export(db, user)


class ImportPayload(BaseModel):
    data: dict


@router.post("/import")
def import_data(body: ImportPayload, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """导入 JSON 备份（覆盖当前账号全部数据）"""
    data = body.data

    # 兼容「自动备份文件」的形状 {"_backup": {...}, "users": {"<用户名>": {<单账号导出>}}}
    # 这样备份目录里的文件可以直接拿去导入恢复，不必手工从 users 里抠出来。
    if isinstance(data, dict) and isinstance(data.get("users"), dict):
        mine = data["users"].get(user.username)
        if mine is None:
            raise HTTPException(
                status_code=400,
                detail="这是一份自动备份文件，其中没有账号「%s」的数据（含：%s）"
                       % (user.username, "、".join(data["users"].keys())),
            )
        data = mine

    if not data or data.get("version") != EXPORT_VERSION:
        raise HTTPException(status_code=400, detail="无效的备份文件格式")

    # 1. 清空当前账号数据
    delete_user_data(db, user.id)
    db.flush()

    # 2. 重建父表，记录 old_id -> new_id 映射
    id_maps = {}
    for model in PARENT_MODELS:
        key = model.__tablename__
        id_maps[key] = {}
        for row in data.get(key, []):
            row = dict(row)
            old_id = row.pop("id", None)
            row.pop("user_id", None)
            convert_cols(model, row)
            # 账户外键映射（资产/保单/借款的 account_id、投资账户的 cash_account_id）
            for fk_col in ("account_id", "cash_account_id"):
                if fk_col in row and row[fk_col] is not None:
                    row[fk_col] = id_maps.get("accounts", {}).get(row[fk_col])
            obj = model(**row, user_id=user.id)
            db.add(obj)
            db.flush()
            if old_id is not None:
                id_maps[key][old_id] = obj.id

    # 3. 重建子表（外键按映射转换）
    for model in CHILD_MODELS:
        key = model.__tablename__
        for row in data.get(key, []):
            row = dict(row)
            row.pop("id", None)
            row.pop("user_id", None)
            convert_cols(model, row)
            for fk_col in ("asset_id", "account_id", "investment_account_id", "category_id",
                           "from_account_id", "to_account_id", "loan_id", "policy_id"):
                if fk_col in row and row[fk_col] is not None:
                    parent_key = {
                        "asset_id": "assets",
                        "account_id": "accounts",
                        "investment_account_id": "investment_accounts",
                        "category_id": "categories",
                        "from_account_id": "accounts",
                        "to_account_id": "accounts",
                        "loan_id": "loans",
                        "policy_id": "insurance_policies",
                    }[fk_col]
                    row[fk_col] = id_maps.get(parent_key, {}).get(row[fk_col])
            try:
                obj = model(**row, user_id=user.id)
                db.add(obj)
            except TypeError:
                continue

    # 4. 重建附件（record_id 按模块映射到新 id）
    module_to_table = {
        "transaction": "transactions",
        "loan": "loans",
        "insurance": "insurance_policies",
        "asset": "assets",
        "financial": "investment_accounts",
        "account": "accounts",
    }
    for row in data.get("attachments", []):
        row = dict(row)
        row.pop("id", None)
        row.pop("user_id", None)
        rid = row.get("record_id")
        if rid is not None:
            table = module_to_table.get(row.get("module"))
            if table:
                row["record_id"] = id_maps.get(table, {}).get(rid)
        try:
            db.add(Attachment(**row, user_id=user.id))
        except TypeError:
            continue

    # 5. 重建提醒规则（不含已读记录，导入后重新提醒）
    for row in data.get("reminder_rules", []):
        row = dict(row)
        row.pop("id", None)
        row.pop("user_id", None)
        try:
            db.add(ReminderRule(**row, user_id=user.id))
        except TypeError:
            continue

    # 备份文件可能来自旧版本，其中的借款 status 是写入时的快照，未必与金额一致；
    # 导入后立即按「本金 − 已收/已还」重算，避免把矛盾状态带进新库。
    from ..seed import sync_loan_status

    db.flush()
    sync_loan_status(db)

    db.commit()
    return {"ok": True, "message": "数据导入成功（覆盖当前账号）"}


# ---------------------------------------------------------------------------
# 回收站（删除归档，v1.9.0）
# ---------------------------------------------------------------------------
@router.get("/deleted")
def list_deleted(
    limit: int = Query(200, ge=1, le=2000),
    module: str | None = Query(None, description="按原表名过滤，如 policy_payments"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出本账号被删除并归档的记录（只读，供事后找回）。

    归档表只写不读、不参与任何统计与对账，所以这里的结果**不代表当前账目里的数据**。
    """
    import json

    q = db.query(DeletedRecord).filter(DeletedRecord.user_id == user.id)
    if module:
        q = q.filter(DeletedRecord.module == module)
    rows = q.order_by(DeletedRecord.deleted_at.desc(), DeletedRecord.id.desc()).limit(limit).all()

    out = []
    for r in rows:
        try:
            payload = json.loads(r.payload) if r.payload else {}
        except ValueError:
            payload = {}
        try:
            context = json.loads(r.context) if r.context else None
        except ValueError:
            context = None
        out.append({
            "id": r.id,
            "module": r.module,
            "record_id": r.record_id,
            "label": r.label,
            "deleted_at": r.deleted_at.isoformat() if r.deleted_at else None,
            "context": context,
            "payload": payload,
        })

    # 分组统计（供界面做筛选器）
    agg: dict[str, int] = {}
    for r in db.query(DeletedRecord).filter(DeletedRecord.user_id == user.id).all():
        agg[r.module] = agg.get(r.module, 0) + 1

    return {
        "total": sum(agg.values()),
        "modules": [{"module": k, "count": v} for k, v in sorted(agg.items(), key=lambda x: -x[1])],
        "items": out,
    }


@router.get("/deleted/export")
def export_deleted(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """导出全部删除归档为 JSON（存档留底用；同样不参与账目）"""
    import json
    from datetime import datetime

    rows = db.query(DeletedRecord).filter(DeletedRecord.user_id == user.id) \
        .order_by(DeletedRecord.deleted_at.asc(), DeletedRecord.id.asc()).all()
    items = []
    for r in rows:
        try:
            payload = json.loads(r.payload) if r.payload else {}
        except ValueError:
            payload = {}
        try:
            context = json.loads(r.context) if r.context else None
        except ValueError:
            context = None
        items.append({
            "module": r.module, "record_id": r.record_id, "label": r.label,
            "deleted_at": r.deleted_at.isoformat() if r.deleted_at else None,
            "context": context, "payload": payload,
        })
    return {
        "exported_at": datetime.now().isoformat(),
        "username": user.username,
        "count": len(items),
        "note": "这是删除归档（回收站）的导出，不是账目数据。恢复需人工把 payload 重新录入。",
        "items": items,
    }


# ---------------------------------------------------------------------------
# 自动备份的状态与手动触发
# ---------------------------------------------------------------------------
@router.get("/backup/status")
def backup_status():
    """备份目录、保留份数、最近一份是否可用（不读数据库）。"""
    return backup.status()


@router.post("/backup/now")
def backup_now(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """立刻写一份备份（**含全部账号**，不只当前账号）。

    日常由后台线程每日自动写一份；这里用于「升级前手动留一份」。
    """
    try:
        res = backup.run_backup(db, reason="manual")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="备份失败：%s: %s" % (type(exc).__name__, exc))
    return {
        "ok": True,
        "file": res["file"],
        "size": res["size"],
        "users": res["users"],
        "removed": res["removed"],
        "dir": backup.backup_dir(),
        "message": "已写出 %s（%.1f KB，覆盖 %d 个账号）"
                   % (res["file"], res["size"] / 1024.0, len(res["users"])),
    }


@router.get("/backup/files")
def backup_files():
    """列出备份文件（最新在前）。"""
    import os
    from datetime import datetime

    files = list(reversed(backup.list_files()))
    out = []
    for path in files:
        try:
            st = os.stat(path)
        except OSError:
            continue
        out.append({
            "name": os.path.basename(path),
            "size": st.st_size,
            "at": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        })
    return {"dir": backup.backup_dir(), "keep": backup.keep_count(), "files": out}
