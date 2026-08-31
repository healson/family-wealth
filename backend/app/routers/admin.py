from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import USER_SCOPED_MODELS, get_current_user
from ..database import get_db
from ..models import Category, CustomOption, User

router = APIRouter(
    prefix="/api/admin",
    tags=["管理"],
    dependencies=[Depends(get_current_user)],
)

# 清空记录时保留分类信息（内置分类 + 用户自定义分类）
_RESET_EXCLUDE = {Category, CustomOption}


@router.post("/reset-data")
def reset_data(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """清空当前登录账号的所有业务记录（保单/账户/收支/资产等），保留账号本身与分类信息（内置+自定义分类）"""
    for model in USER_SCOPED_MODELS:
        if model in _RESET_EXCLUDE:
            continue
        db.query(model).filter(model.user_id == user.id).delete()
    db.commit()
    return {"ok": True, "message": "当前账号的记录已清空（分类信息已保留）"}
