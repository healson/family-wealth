import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Attachment, User
from ..schemas import AttachmentOut
from ..utils import archive_deleted

router = APIRouter(
    prefix="/api/attachments",
    tags=["附件"],
    dependencies=[Depends(get_current_user)],
)

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data"))
MAX_SIZE = 20 * 1024 * 1024  # 单文件 20MB

ALLOWED_EXT = {
    # 图片
    "jpg", "jpeg", "png", "gif", "webp", "bmp",
    # 文档
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "csv", "md",
    # 压缩
    "zip", "rar", "7z",
}

MODULES = {"transaction", "loan", "insurance", "asset", "financial", "account"}


def _upload_root(user_id: int) -> str:
    root = os.path.join(DATA_DIR, "uploads", str(user_id))
    os.makedirs(root, exist_ok=True)
    return root


def _safe_ext(filename: str) -> str:
    _, ext = os.path.splitext(filename)
    return ext.lower().lstrip(".")


@router.post("/upload", response_model=AttachmentOut)
def upload_file(
    file: UploadFile = File(...),
    module: str = Form(...),
    record_id: int | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if module not in MODULES:
        raise HTTPException(status_code=400, detail="无效的模块")
    ext = _safe_ext(file.filename or "")
    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型：.{ext or '未知'}")
    # 读取内容（同时校验大小）
    content = file.file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="文件超过 20MB 限制")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="空文件")

    stored_name = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(_upload_root(user.id), stored_name)
    with open(path, "wb") as f:
        f.write(content)

    att = Attachment(
        user_id=user.id,
        module=module,
        record_id=record_id,
        filename=file.filename or stored_name,
        stored_name=stored_name,
        mime=file.content_type or "application/octet-stream",
        size=len(content),
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return att


@router.get("", response_model=list[AttachmentOut])
def list_attachments(
    module: str,
    record_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Attachment).filter(
        Attachment.user_id == user.id, Attachment.module == module
    )
    if record_id is not None:
        q = q.filter(Attachment.record_id == record_id)
    return q.order_by(Attachment.id.asc()).all()


@router.post("/link")
def link_attachments(
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """将已上传的附件关联到某条记录（用于新建记录后回填 record_id）"""
    module = body.get("module")
    record_id = body.get("record_id")
    ids = body.get("ids") or []
    if module not in MODULES or not record_id or not isinstance(ids, list):
        raise HTTPException(status_code=400, detail="参数错误")
    for att_id in ids:
        att = db.query(Attachment).filter(
            Attachment.id == att_id, Attachment.user_id == user.id
        ).first()
        if att:
            att.module = module
            att.record_id = record_id
    db.commit()
    return {"ok": True}


@router.delete("/{attachment_id}")
def delete_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    att = db.query(Attachment).filter(
        Attachment.id == attachment_id, Attachment.user_id == user.id
    ).first()
    if att is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    path = os.path.join(_upload_root(user.id), att.stored_name)
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass
    archive_deleted(db, att)  # 删除前归档，供事后找回（只写不读）
    db.delete(att)
    db.commit()
    return {"ok": True}


@router.get("/{attachment_id}/file")
def get_file(
    attachment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    att = db.query(Attachment).filter(
        Attachment.id == attachment_id, Attachment.user_id == user.id
    ).first()
    if att is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    path = os.path.join(_upload_root(user.id), att.stored_name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="文件已丢失")
    return FileResponse(path, media_type=att.mime, filename=att.filename)
