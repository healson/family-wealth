import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import (
    Account,
    AccountTransaction,
    AISetting,
    Asset,
    AssetValuation,
    Attachment,
    Category,
    CustomOption,
    DailyPnl,
    InsurancePolicy,
    InvestmentAccount,
    InvestmentFlow,
    Loan,
    LoanPayment,
    PolicyPayment,
    ReminderDismissal,
    ReminderRule,
    ScheduledTransaction,
    Transaction,
    TransactionTemplate,
    Transfer,
    User,
)

SECRET_KEY = os.environ.get("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "168"))  # 默认 7 天

security = HTTPBearer(auto_error=False)


def hash_password(password: str, salt: Optional[str] = None) -> str:
    """PBKDF2-SHA256，标准库实现，避免额外依赖"""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


def create_token(user_id: int, username: str, is_admin: int = 0) -> str:
    payload = {
        "sub": str(user_id),
        "username": username,
        "is_admin": is_admin,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    # 调试模式（仅用于无头浏览器截图验证等开发场景，生产环境务必不要开启）
    if os.environ.get("TEST_AUTH") == "1":
        admin = db.query(User).filter(User.username == "admin").first()
        if admin:
            return admin
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = int(payload["sub"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


# 删除账号时需要清空的业务表（SQLite 外键级联不可靠，手动删除）
USER_SCOPED_MODELS = [
    AISetting,
    CustomOption,
    ScheduledTransaction,
    TransactionTemplate,
    LoanPayment,
    Loan,
    InvestmentFlow,
    DailyPnl,
    InvestmentAccount,
    Transfer,
    AccountTransaction,
    Account,
    PolicyPayment,
    InsurancePolicy,
    AssetValuation,
    Asset,
    Transaction,
    Category,
    Attachment,
    ReminderRule,
    ReminderDismissal,
]


def delete_user_data(db: Session, user_id: int):
    """清空某账号的全部业务数据"""
    for model in USER_SCOPED_MODELS:
        db.query(model).filter(model.user_id == user_id).delete()
