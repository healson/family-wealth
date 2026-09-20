from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Account, Transfer, User
from ..schemas import TransferCreate, TransferOut
from ..utils import archive_deleted, coerce_money

router = APIRouter(
    prefix="/api/transfers",
    tags=["转账"],
    dependencies=[Depends(get_current_user)],
)


def _get_owned_account(db: Session, account_id: int, user_id: int) -> Account:
    account = db.query(Account).filter(Account.id == account_id, Account.user_id == user_id).first()
    if account is None:
        raise HTTPException(status_code=404, detail="账户不存在")
    return account


@router.get("", response_model=list[TransferOut])
def list_transfers(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Transfer).filter(Transfer.user_id == user.id)\
        .order_by(Transfer.date.desc(), Transfer.id.desc()).all()


@router.post("", response_model=TransferOut)
def create_transfer(body: TransferCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    data = coerce_money(body.model_dump())
    if data["from_account_id"] == data["to_account_id"]:
        raise HTTPException(status_code=400, detail="转出与转入账户不能相同")
    from_account = _get_owned_account(db, data["from_account_id"], user.id)
    to_account = _get_owned_account(db, data["to_account_id"], user.id)
    amount = float(data["amount"])
    if amount <= 0:
        raise HTTPException(status_code=400, detail="转账金额必须大于 0")

    transfer = Transfer(**data, user_id=user.id)
    # 自动同步余额：转出扣减，转入增加
    from_account.balance = float(from_account.balance or 0) - amount
    to_account.balance = float(to_account.balance or 0) + amount
    db.add(transfer)
    db.commit()
    db.refresh(transfer)
    return transfer


@router.delete("/{transfer_id}")
def delete_transfer(transfer_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    transfer = db.query(Transfer).filter(Transfer.id == transfer_id, Transfer.user_id == user.id).first()
    if transfer is None:
        raise HTTPException(status_code=404, detail="转账记录不存在")
    # 反向恢复余额
    from_account = _get_owned_account(db, transfer.from_account_id, user.id)
    to_account = _get_owned_account(db, transfer.to_account_id, user.id)
    amount = float(transfer.amount)
    from_account.balance = float(from_account.balance or 0) + amount
    to_account.balance = float(to_account.balance or 0) - amount
    archive_deleted(db, transfer)  # 删除前归档，供事后找回（只写不读）
    db.delete(transfer)
    db.commit()
    return {"ok": True}
