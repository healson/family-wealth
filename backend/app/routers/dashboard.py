from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import (
    Account,
    AccountTransaction,
    Asset,
    AssetValuation,
    Category,
    DailyPnl,
    InsurancePolicy,
    InvestmentAccount,
    InvestmentFlow,
    Loan,
    LoanPayment,
    Transaction,
    User,
)
from ..utils import asset_cash_paid, last_n_months, reconcile_accounts

router = APIRouter(
    prefix="/api/dashboard",
    tags=["仪表盘"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/summary")
def summary(
    period: str = "month",  # week / month / year
    ref: str | None = None,  # 参考日期 YYYY-MM-DD，默认今天
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    uid = user.id
    today = date.today()
    ref_date = today
    if ref:
        try:
            ref_date = date.fromisoformat(ref)
        except ValueError:
            pass

    # ---- 周期起止 ----
    if period == "week":
        start = ref_date - timedelta(days=ref_date.weekday())
        end = start + timedelta(days=6)
        period_label = f"{start:%m-%d} ~ {end:%m-%d}"
    elif period == "year":
        start = date(ref_date.year, 1, 1)
        end = date(ref_date.year, 12, 31)
        period_label = f"{ref_date.year} 年"
    else:
        start = date(ref_date.year, ref_date.month, 1)
        end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        period_label = f"{ref_date.year}年{ref_date.month}月"

    # 各类资产汇总（仅当前用户）
    fixed_asset_value = db.query(func.coalesce(func.sum(Asset.current_value), 0))\
        .filter(Asset.user_id == uid).scalar() or 0
    fixed_asset_loan = db.query(func.coalesce(func.sum(Asset.loan_balance), 0))\
        .filter(Asset.user_id == uid).scalar() or 0
    account_balance = db.query(func.coalesce(func.sum(Account.balance), 0))\
        .filter(Account.user_id == uid).scalar() or 0
    financial_value = db.query(func.coalesce(func.sum(InvestmentAccount.balance), 0))\
        .filter(InvestmentAccount.user_id == uid).scalar() or 0
    # 本月投资盈亏（来自日盈亏记录）
    month_start = today.replace(day=1)
    month_pnl = db.query(func.coalesce(func.sum(DailyPnl.pnl), 0))\
        .filter(DailyPnl.user_id == uid, DailyPnl.date >= month_start).scalar() or 0

    # 借款汇总（应收款=借出未还，应付款=借入未还）+ 借款列表
    receivable = 0.0
    payable = 0.0
    overdue_loans = 0
    loan_list = []
    for l in db.query(Loan).filter(Loan.user_id == uid).all():
        paid = sum(float(p.amount) for p in l.payments)
        remaining = float(l.amount) - paid
        overdue = bool(l.due_date is not None and l.due_date < today and remaining > 0)
        if remaining > 0:
            if l.type == "借出":
                receivable += remaining
            else:
                payable += remaining
            if l.due_date is not None and l.due_date < today:
                overdue_loans += 1
        loan_list.append({
            "id": l.id, "type": l.type, "counterparty": l.counterparty,
            "amount": round(float(l.amount), 2), "paid": round(paid, 2),
            "remaining": round(remaining, 2),
            "due_date": l.due_date.isoformat() if l.due_date else None,
            "overdue": overdue,
        })
    loan_list.sort(key=lambda x: (x["remaining"] <= 0, x["due_date"] or "9999-99-99"))

    total_assets = float(fixed_asset_value) + float(account_balance) + float(financial_value) + float(receivable)
    total_liabilities = float(fixed_asset_loan) + float(payable)
    net_worth = total_assets - total_liabilities

    # 本月收支（保留兼容）
    month_income = db.query(func.coalesce(func.sum(Transaction.amount), 0))\
        .filter(Transaction.type == "收入", Transaction.user_id == uid, Transaction.date >= month_start).scalar() or 0
    month_expense = db.query(func.coalesce(func.sum(Transaction.amount), 0))\
        .filter(Transaction.type == "支出", Transaction.user_id == uid, Transaction.date >= month_start).scalar() or 0

    # ---- 所选周期收支与分类统计 ----
    period_income = db.query(func.coalesce(func.sum(Transaction.amount), 0))\
        .filter(Transaction.type == "收入", Transaction.user_id == uid,
                Transaction.date >= start, Transaction.date <= end).scalar() or 0
    period_expense = db.query(func.coalesce(func.sum(Transaction.amount), 0))\
        .filter(Transaction.type == "支出", Transaction.user_id == uid,
                Transaction.date >= start, Transaction.date <= end).scalar() or 0

    def _category_stats(ttype: str):
        rows = db.query(Transaction.category_id, func.sum(Transaction.amount))\
            .filter(Transaction.type == ttype, Transaction.user_id == uid,
                    Transaction.date >= start, Transaction.date <= end)\
            .group_by(Transaction.category_id).all()
        result = []
        for cid, amt in rows:
            if cid is None:
                result.append({"name": "未分类", "value": round(float(amt), 2)})
                continue
            cat = db.get(Category, cid)
            result.append({"name": cat.name if cat else "未分类", "value": round(float(amt), 2)})
        result.sort(key=lambda x: x["value"], reverse=True)
        return result

    income_categories = _category_stats("收入")
    expense_categories = _category_stats("支出")

    # ---- 收支趋势（按周期粒度） ----
    trend = []
    if period == "week":
        # 近 8 周
        for i in range(7, -1, -1):
            w_start = start - timedelta(weeks=i)
            w_end = w_start + timedelta(days=6)
            income = db.query(func.coalesce(func.sum(Transaction.amount), 0))\
                .filter(Transaction.type == "收入", Transaction.user_id == uid,
                        Transaction.date >= w_start, Transaction.date <= w_end).scalar() or 0
            expense = db.query(func.coalesce(func.sum(Transaction.amount), 0))\
                .filter(Transaction.type == "支出", Transaction.user_id == uid,
                        Transaction.date >= w_start, Transaction.date <= w_end).scalar() or 0
            trend.append({"month": f"{w_start:%m-%d}", "income": float(income), "expense": float(expense)})
    elif period == "year":
        # 近 5 年
        for y in range(ref_date.year - 4, ref_date.year + 1):
            income = db.query(func.coalesce(func.sum(Transaction.amount), 0))\
                .filter(Transaction.type == "收入", Transaction.user_id == uid,
                        func.strftime("%Y", Transaction.date) == f"{y:04d}").scalar() or 0
            expense = db.query(func.coalesce(func.sum(Transaction.amount), 0))\
                .filter(Transaction.type == "支出", Transaction.user_id == uid,
                        func.strftime("%Y", Transaction.date) == f"{y:04d}").scalar() or 0
            trend.append({"month": f"{y}", "income": float(income), "expense": float(expense)})
    else:
        # 近 12 个月
        months = last_n_months(12)
        for y, m in months:
            prefix = f"{y:04d}-{m:02d}"
            income = db.query(func.coalesce(func.sum(Transaction.amount), 0))\
                .filter(Transaction.type == "收入", Transaction.user_id == uid,
                        func.strftime("%Y-%m", Transaction.date) == prefix).scalar() or 0
            expense = db.query(func.coalesce(func.sum(Transaction.amount), 0))\
                .filter(Transaction.type == "支出", Transaction.user_id == uid,
                        func.strftime("%Y-%m", Transaction.date) == prefix).scalar() or 0
            trend.append({"month": f"{y}-{m:02d}", "income": float(income), "expense": float(expense)})

    # 金融资产月度盈亏趋势（近 12 个月，正=盈利 负=亏损）
    financial_trend = []
    for y, m in last_n_months(12):
        prefix = f"{y:04d}-{m:02d}"
        pnl = db.query(func.coalesce(func.sum(DailyPnl.pnl), 0))\
            .filter(DailyPnl.user_id == uid, func.strftime("%Y-%m", DailyPnl.date) == prefix).scalar() or 0
        financial_trend.append({"month": f"{y}-{m:02d}", "pnl": round(float(pnl), 2)})

    # 现金账户月度净存取趋势（近 12 个月，存入-取出）
    cash_trend = []
    for y, m in last_n_months(12):
        prefix = f"{y:04d}-{m:02d}"
        dep = db.query(func.coalesce(func.sum(AccountTransaction.amount), 0))\
            .filter(AccountTransaction.user_id == uid, AccountTransaction.type == "存入",
                    func.strftime("%Y-%m", AccountTransaction.date) == prefix).scalar() or 0
        wd = db.query(func.coalesce(func.sum(AccountTransaction.amount), 0))\
            .filter(AccountTransaction.user_id == uid, AccountTransaction.type == "取出",
                    func.strftime("%Y-%m", AccountTransaction.date) == prefix).scalar() or 0
        cash_trend.append({"month": f"{y}-{m:02d}", "net": round(float(dep) - float(wd), 2)})

    # 固定资产价值趋势（当前用户的估值记录）
    val_rows = db.query(AssetValuation).filter(AssetValuation.user_id == uid)\
        .order_by(AssetValuation.date.asc()).all()
    val_map: dict[str, float] = {}
    for v in val_rows:
        key = v.date.strftime("%Y-%m")
        val_map[key] = val_map.get(key, 0) + float(v.value)
    fixed_trend = [{"month": k, "value": round(v, 2)} for k, v in sorted(val_map.items())]

    # 近期收支记录
    recent = db.query(Transaction).filter(Transaction.user_id == uid)\
        .order_by(Transaction.date.desc(), Transaction.id.desc()).limit(8).all()
    recent_out = [
        {
            "id": t.id, "type": t.type, "amount": float(t.amount),
            "date": t.date.isoformat(), "note": t.note,
            "category": t.category.name if t.category else None,
            "account": t.account.name if t.account else None,
        }
        for t in recent
    ]

    # 30 天内需缴费/到期的保单提醒（当前用户）
    soon = today + timedelta(days=30)
    policies = db.query(InsurancePolicy).filter(
        InsurancePolicy.user_id == uid,
        InsurancePolicy.status == "有效",
        InsurancePolicy.next_due_date.isnot(None),
        InsurancePolicy.next_due_date <= soon,
    ).all()
    expiring = [
        {
            "id": p.id, "product_name": p.product_name, "company": p.company,
            "next_due_date": p.next_due_date.isoformat() if p.next_due_date else None,
            "premium": float(p.premium),
            "days": (p.next_due_date - today).days,
        }
        for p in policies
    ]
    expiring.sort(key=lambda x: x["days"])

    # 保单列表（全部保单）
    policy_list = [
        {
            "id": p.id, "product_name": p.product_name, "company": p.company,
            "premium": round(float(p.premium), 2),
            "next_due_date": p.next_due_date.isoformat() if p.next_due_date else None,
            "end_date": p.end_date.isoformat() if p.end_date else None,
            "status": p.status,
        }
        for p in db.query(InsurancePolicy).filter(InsurancePolicy.user_id == uid).all()
    ]
    policy_list.sort(key=lambda x: x["next_due_date"] or "9999-99-99")

    # 最近一个月到期提醒（保单缴费 + 借款还款，合并排序）
    upcoming = []
    for p in policies:
        upcoming.append({
            "kind": "保单", "title": f"{p.product_name}（{p.company}）",
            "date": p.next_due_date.isoformat(), "amount": round(float(p.premium), 2),
            "days": (p.next_due_date - today).days,
        })
    for l in db.query(Loan).filter(Loan.user_id == uid).all():
        if l.due_date is None or not (today <= l.due_date <= soon):
            continue
        paid = sum(float(p.amount) for p in l.payments)
        remaining = float(l.amount) - paid
        if remaining <= 0:
            continue
        upcoming.append({
            "kind": "借款", "title": f"{l.counterparty}（{'借出' if l.type == '借出' else '借入'}）",
            "date": l.due_date.isoformat(), "amount": round(remaining, 2),
            "days": (l.due_date - today).days,
        })
    upcoming.sort(key=lambda x: x["days"])

    # ---- 本月资金流向（流入/流出分项） ----
    month_start = today.replace(day=1)
    month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    month_income = db.query(func.coalesce(func.sum(Transaction.amount), 0))\
        .filter(Transaction.type == "收入", Transaction.user_id == uid,
                Transaction.date >= month_start, Transaction.date <= month_end).scalar() or 0
    month_expense = db.query(func.coalesce(func.sum(Transaction.amount), 0))\
        .filter(Transaction.type == "支出", Transaction.user_id == uid,
                Transaction.date >= month_start, Transaction.date <= month_end).scalar() or 0
    loan_out = db.query(func.coalesce(func.sum(Loan.amount), 0))\
        .filter(Loan.type == "借出", Loan.user_id == uid,
                Loan.date >= month_start, Loan.date <= month_end).scalar() or 0
    loan_in = db.query(func.coalesce(func.sum(Loan.amount), 0))\
        .filter(Loan.type == "借入", Loan.user_id == uid,
                Loan.date >= month_start, Loan.date <= month_end).scalar() or 0
    receive = db.query(func.coalesce(func.sum(LoanPayment.amount), 0))\
        .join(Loan, LoanPayment.loan_id == Loan.id)\
        .filter(Loan.type == "借出", LoanPayment.user_id == uid,
                LoanPayment.date >= month_start, LoanPayment.date <= month_end).scalar() or 0
    repay = db.query(func.coalesce(func.sum(LoanPayment.amount), 0))\
        .join(Loan, LoanPayment.loan_id == Loan.id)\
        .filter(Loan.type == "借入", LoanPayment.user_id == uid,
                LoanPayment.date >= month_start, LoanPayment.date <= month_end).scalar() or 0
    invest_in = db.query(func.coalesce(func.sum(InvestmentFlow.amount), 0))\
        .filter(InvestmentFlow.type == "转入", InvestmentFlow.user_id == uid,
                InvestmentFlow.date >= month_start, InvestmentFlow.date <= month_end).scalar() or 0
    invest_out = db.query(func.coalesce(func.sum(InvestmentFlow.amount), 0))\
        .filter(InvestmentFlow.type == "转出", InvestmentFlow.user_id == uid,
                InvestmentFlow.date >= month_start, InvestmentFlow.date <= month_end).scalar() or 0
    from ..models import PolicyPayment

    policy_paid = db.query(func.coalesce(func.sum(PolicyPayment.amount), 0))\
        .filter(PolicyPayment.user_id == uid,
                PolicyPayment.date >= month_start, PolicyPayment.date <= month_end).scalar() or 0
    asset_bought = sum(
        asset_cash_paid(a) for a in db.query(Asset).filter(
            Asset.user_id == uid, Asset.purchase_date.isnot(None),
            Asset.purchase_date >= month_start, Asset.purchase_date <= month_end,
        ).all()
    )

    inflow = {
        "收入": round(float(month_income), 2),
        "借入": round(float(loan_in), 2),
        "收款": round(float(receive), 2),
        "投资转出": round(float(invest_out), 2),
    }
    inflow["total"] = round(sum(inflow.values()), 2)
    outflow = {
        "支出": round(float(month_expense), 2),
        "借出": round(float(loan_out), 2),
        "还款": round(float(repay), 2),
        "保单缴费": round(float(policy_paid), 2),
        "资产购入": round(float(asset_bought), 2),
        "投资转入": round(float(invest_in), 2),
    }
    outflow["total"] = round(sum(outflow.values()), 2)
    cash_flow = {"inflow": inflow, "outflow": outflow, "net": round(inflow["total"] - outflow["total"], 2)}

    # ---- 余额对账校验：应有余额 = 期初基准 + 全部资金流水，与实际余额对比 ----
    # 计算逻辑已抽到 utils.reconcile_accounts（v1.9.0）—— 启动自检与 /api/health
    # 也调同一个函数，避免两处各写一遍导致对账口径漂移。
    reconciliation = reconcile_accounts(db, uid)

    return {
        "total_assets": round(total_assets, 2),
        "total_liabilities": round(total_liabilities, 2),
        "net_worth": round(net_worth, 2),
        # 金融口径（不含固定资产）：现金 + 投资 + 借出应收款；金融负债 = 借入应付款
        "financial_assets": round(float(account_balance) + float(financial_value) + float(receivable), 2),
        "financial_liabilities": round(float(payable), 2),
        "financial_net": round(float(account_balance) + float(financial_value) + float(receivable) - float(payable), 2),
        "financial_breakdown": [
            {"name": "现金账户", "value": round(float(account_balance), 2)},
            {"name": "金融投资", "value": round(float(financial_value), 2)},
            {"name": "借出应收款", "value": round(receivable, 2)},
        ],
        "month_income": round(float(month_income), 2),
        "month_expense": round(float(month_expense), 2),
        "period": {"type": period, "label": period_label, "start": start.isoformat(), "end": end.isoformat()},
        "period_income": round(float(period_income), 2),
        "period_expense": round(float(period_expense), 2),
        "period_balance": round(float(period_income) - float(period_expense), 2),
        "income_categories": income_categories,
        "expense_categories": expense_categories,
        "category_expense": expense_categories,
        "asset_breakdown": [
            {"name": "固定资产", "value": round(float(fixed_asset_value), 2)},
            {"name": "现金账户", "value": round(float(account_balance), 2)},
            {"name": "金融资产", "value": round(float(financial_value), 2)},
            {"name": "借出应收款", "value": round(receivable, 2)},
        ],
        "net_worth_breakdown": [
            {"name": "固定资产净值", "value": round(float(fixed_asset_value) - float(fixed_asset_loan), 2)},
            {"name": "现金账户", "value": round(float(account_balance), 2)},
            {"name": "金融资产", "value": round(float(financial_value), 2)},
            {"name": "借出应收款", "value": round(receivable, 2)},
        ],
        "financial_profit": round(float(month_pnl), 2),
        "month_pnl": round(float(month_pnl), 2),
        "receivable": round(receivable, 2),
        "payable": round(payable, 2),
        "overdue_loans": overdue_loans,
        "income_expense_trend": trend,
        "financial_trend": financial_trend,
        "cash_trend": cash_trend,
        "fixed_asset_trend": fixed_trend,
        "loans": loan_list,
        "policies": policy_list,
        "upcoming": upcoming,
        "cash_flow": cash_flow,
        "reconciliation": reconciliation,
        "recent_transactions": recent_out,
        "insurance_expiring": expiring,
        "category_expense": expense_categories,
    }
