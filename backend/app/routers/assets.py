from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Asset, AssetValuation, User
from ..schemas import (
    AssetCreate,
    AssetOut,
    AssetUpdate,
    ValuationCreate,
    ValuationOut,
)
from ..utils import apply_account_delta, asset_cash_paid, coerce_money

router = APIRouter(
    prefix="/api/assets",
    tags=["固定资产"],
    dependencies=[Depends(get_current_user)],
)


def _apply_asset_balance(db, asset, sign=1):
    """固定资产购入联动余额：购入价「全款部分」（购入价 − 贷款余额）从付款账户支出（−）。

    贷款部分由银行直接支付给卖方、不经家庭账户，故不从账户扣款。
    """
    if not asset.account_id:
        return
    cash_paid = asset_cash_paid(asset)
    if cash_paid <= 0:
        return
    apply_account_delta(db, asset.account_id, -cash_paid * sign)


def _to_out(asset: Asset) -> AssetOut:
    out = AssetOut.model_validate(asset)
    out.net_value = float(asset.current_value) - float(asset.loan_balance)
    return out


def _get_owned_asset(db: Session, asset_id: int, user_id: int) -> Asset:
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.user_id == user_id).first()
    if asset is None:
        raise HTTPException(status_code=404, detail="资产不存在")
    return asset


@router.get("", response_model=list[AssetOut])
def list_assets(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    assets = db.query(Asset).filter(Asset.user_id == user.id).order_by(Asset.created_at.desc()).all()
    return [_to_out(a) for a in assets]


@router.post("", response_model=AssetOut)
def create_asset(body: AssetCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    data = coerce_money(body.model_dump())
    asset = Asset(**data, user_id=user.id)
    db.add(asset)
    db.flush()
    _apply_asset_balance(db, asset, 1)  # 全款购入从付款账户支出
    db.commit()
    db.refresh(asset)
    return _to_out(asset)


@router.put("/{asset_id}", response_model=AssetOut)
def update_asset(asset_id: int, body: AssetUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    asset = _get_owned_asset(db, asset_id, user.id)
    data = coerce_money(body.model_dump(exclude_unset=True))
    # 先回滚旧影响，再应用新影响
    _apply_asset_balance(db, asset, -1)
    for k, v in data.items():
        setattr(asset, k, v)
    db.flush()
    _apply_asset_balance(db, asset, 1)
    db.commit()
    db.refresh(asset)
    return _to_out(asset)


@router.delete("/{asset_id}")
def delete_asset(asset_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    asset = _get_owned_asset(db, asset_id, user.id)
    _apply_asset_balance(db, asset, -1)  # 反向恢复余额
    db.delete(asset)
    db.commit()
    return {"ok": True}


# ---------- 估值历史 ----------
@router.get("/{asset_id}/valuations", response_model=list[ValuationOut])
def list_valuations(asset_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    asset = _get_owned_asset(db, asset_id, user.id)
    return asset.valuations


@router.post("/{asset_id}/valuations", response_model=ValuationOut)
def add_valuation(asset_id: int, body: ValuationCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    asset = _get_owned_asset(db, asset_id, user.id)
    v = AssetValuation(asset_id=asset_id, user_id=user.id, value=float(body.value), date=body.date, note=body.note)
    db.add(v)
    # 同步更新当前估值
    asset.current_value = float(body.value)
    asset.valuation_date = body.date
    db.commit()
    db.refresh(v)
    return v


@router.delete("/{asset_id}/valuations/{valuation_id}")
def delete_valuation(asset_id: int, valuation_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    v = db.query(AssetValuation).filter(
        AssetValuation.id == valuation_id,
        AssetValuation.asset_id == asset_id,
        AssetValuation.user_id == user.id,
    ).first()
    if v is None:
        raise HTTPException(status_code=404, detail="估值记录不存在")
    db.delete(v)
    db.commit()
    return {"ok": True}
