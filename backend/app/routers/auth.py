from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import (
    create_token,
    delete_user_data,
    get_current_user,
    hash_password,
    require_admin,
    verify_password,
)
from ..database import get_db
from ..models import User
from ..schemas import (
    AdminUserUpdate,
    LoginRequest,
    TokenResponse,
    UserCreate,
    UserOut,
    UserUpdate,
)

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return TokenResponse(
        token=create_token(user.id, user.username, user.is_admin),
        username=user.username,
        is_admin=bool(user.is_admin),
    )


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "username": user.username, "is_admin": bool(user.is_admin)}


@router.put("/me")
def update_me(body: UserUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """修改自己的用户名"""
    if not body.username or body.username.strip() == user.username:
        raise HTTPException(status_code=400, detail="未提供新用户名")
    username = body.username.strip()
    if len(username) < 2:
        raise HTTPException(status_code=400, detail="用户名至少 2 个字符")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="用户名已被占用")
    user.username = username
    db.commit()
    return {"ok": True, "message": "用户名已修改，请重新登录", "username": username}


@router.post("/change-password")
def change_password(
    old_password: str,
    new_password: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 位")
    user.password_hash = hash_password(new_password)
    db.commit()
    return {"ok": True}


# ---------- 账号管理（管理员） ----------
@router.get("/users", response_model=list[UserOut])
def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(User).order_by(User.id.asc()).all()


@router.post("/users", response_model=UserOut)
def create_user(body: UserCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    username = body.username.strip()
    if len(username) < 2:
        raise HTTPException(status_code=400, detail="用户名至少 2 个字符")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 位")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="用户名已被占用")
    user = User(username=username, password_hash=hash_password(body.password), is_admin=0)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}")
def delete_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录的账号")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    delete_user_data(db, user_id)
    db.delete(user)
    db.commit()
    return {"ok": True, "message": f"账号 {user.username} 及其数据已删除"}


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: AdminUserUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理员修改其他账号的用户名和/或密码"""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    if user.is_admin:
        raise HTTPException(status_code=400, detail="不能修改其他管理员账号")
    changed = []
    if body.username is not None and body.username.strip():
        username = body.username.strip()
        if username != user.username:
            if len(username) < 2:
                raise HTTPException(status_code=400, detail="用户名至少 2 个字符")
            if db.query(User).filter(User.username == username).first():
                raise HTTPException(status_code=400, detail="用户名已被占用")
            user.username = username
            changed.append("用户名")
    if body.password is not None and body.password:
        if len(body.password) < 6:
            raise HTTPException(status_code=400, detail="密码至少 6 位")
        user.password_hash = hash_password(body.password)
        changed.append("密码")
    if not changed:
        raise HTTPException(status_code=400, detail="未提供要修改的内容")
    db.commit()
    return user

