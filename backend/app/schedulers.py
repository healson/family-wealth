"""定时交易调度：后台线程每分钟检查到期任务并自动生成收支记录"""
import threading
import time
from datetime import date, timedelta

from sqlalchemy.orm import Session

from .models import ScheduledTransaction, Transaction
from .utils import apply_txn_balance

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def calc_first_next(item: ScheduledTransaction) -> date:
    """从 start_date 开始计算首个执行日（保证不早于 start_date）"""
    if item.frequency == "weekly":
        d = item.start_date
        while d.weekday() != item.day:
            d += timedelta(days=1)
        return d
    if item.frequency == "yearly":
        d = date(item.start_date.year, item.yearly_month or 1, min(item.day, 28))
        # 本年该日已过 → 顺延到下一年；否则创建任务时会立刻补记一笔「生效前」的收支并扣款
        if d < item.start_date:
            d = date(item.start_date.year + 1, item.yearly_month or 1, min(item.day, 28))
        return d
    # monthly
    d = date(item.start_date.year, item.start_date.month, min(item.day, 28))
    if d < item.start_date:
        d = calc_next(item, d)
    return d


def calc_next(item: ScheduledTransaction, last: date) -> date:
    """计算 last 之后的下一执行日"""
    if item.frequency == "weekly":
        d = last + timedelta(days=1)
        while d.weekday() != item.day:
            d += timedelta(days=1)
        return d
    if item.frequency == "yearly":
        return date(last.year + 1, item.yearly_month or 1, min(item.day, 28))
    # monthly：下个月
    y = last.year + last.month // 12
    m = last.month % 12 + 1
    return date(y, m, min(item.day, 28))


def frequency_label(item: ScheduledTransaction) -> str:
    if item.frequency == "weekly":
        return f"每周{WEEKDAY_NAMES[item.day] if 0 <= item.day < 7 else item.day}"
    if item.frequency == "yearly":
        return f"每年{item.yearly_month or 1}月{item.day}日"
    return f"每月{item.day}日"


def run_due(db: Session) -> int:
    """执行所有到期的定时交易，返回生成的记录数"""
    today = date.today()
    items = db.query(ScheduledTransaction).filter(
        ScheduledTransaction.active == 1,
        ScheduledTransaction.next_run_date <= today,
    ).all()
    count = 0
    for it in items:
        if it.end_date and it.next_run_date > it.end_date:
            it.active = 0
            continue
        note = f"⏰{it.name}"
        if it.note:
            note += f"·{it.note}"
        txn = Transaction(
            user_id=it.user_id, type=it.type, amount=it.amount,
            category_id=it.category_id, account_id=it.account_id,
            date=it.next_run_date, note=note[:200],
        )
        db.add(txn)
        apply_txn_balance(db, txn, 1)  # 定时生成的收支同样联动账户余额
        it.last_run_date = it.next_run_date
        it.next_run_date = calc_next(it, it.next_run_date)
        if it.end_date and it.next_run_date > it.end_date:
            it.active = 0
        count += 1
    if count:
        db.commit()
    return count


def _scheduler_loop():
    from .database import SessionLocal

    while True:
        try:
            db = SessionLocal()
            try:
                run_due(db)
            finally:
                db.close()
        except Exception:
            pass
        time.sleep(60)


def start_scheduler():
    """启动后台调度线程（应用启动时调用，daemon 线程）"""
    t = threading.Thread(target=_scheduler_loop, name="scheduled-tx", daemon=True)
    t.start()
