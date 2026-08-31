from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import CustomOption, User
from ..schemas import OptionCreate, OptionOut

router = APIRouter(
    prefix="/api/options",
    tags=["自定义选项"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[OptionOut])
def list_options(module: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取某模块下当前用户的自定义选项值"""
    return db.query(CustomOption).filter(
        CustomOption.user_id == user.id, CustomOption.module == module
    ).order_by(CustomOption.created_at.asc()).all()


@router.post("", response_model=OptionOut)
def create_option(body: OptionCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    value = body.value.strip()
    if not value:
        raise HTTPException(status_code=400, detail="类别不能为空")
    exists = db.query(CustomOption).filter(
        CustomOption.user_id == user.id, CustomOption.module == body.module, CustomOption.value == value
    ).first()
    if exists:
        raise HTTPException(status_code=400, detail="该类别已存在")
    option = CustomOption(user_id=user.id, module=body.module, value=value)
    db.add(option)
    db.commit()
    db.refresh(option)
    return option


@router.delete("/{option_id}")
def delete_option(option_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    option = db.query(CustomOption).filter(CustomOption.id == option_id, CustomOption.user_id == user.id).first()
    if option is None:
        raise HTTPException(status_code=404, detail="选项不存在")
    db.delete(option)
    db.commit()
    return {"ok": True}
