"""
事件特徵（Iteration 20）
────────────────────────
台股個股在營收公布、除權息等事件前後振幅明顯偏大，而這些時點**事先可知**，
是少數能確定提升振幅預測的資訊。

## 營收公布日：為何改用法規排程而非實際公布日

原本打算用 FinMind `TaiwanStockMonthRevenue` 的 `create_time` 當公布日，
實測後放棄——**那是 FinMind 自己的入庫時間戳，不是公司的公布日**：
全部歷史只回補到 128 筆且集中在 2026-04~08（該批資料的重新入庫時間），
更早的記錄根本沒有這個欄位。

改用**法規排程**：台股要求月營收於次月 10 日前公布，故以每月 10 日為事件日。
這反而更好：

  · 完整涵蓋全部歷史，不受 API 資料品質影響
  · 事先可知，前後皆可使用，不構成洩漏
  · 這正是市場實際預期的時間窗（實務上公司多在 1~10 日之間公布）

代價：無法區分「5 日就公布」與「10 日才公布」的個股差異。

## 時序嚴謹性：哪些日期可以「往前看」

判準是「該日期在預測當下是否已經公開」：

| 事件 | 依據 | 可否用於「距離下次」 |
|------|------|-------------------|
| 月營收 | 法規排程（每月 10 日） | ✅ 法規決定，永遠事先可知 |
| 除權息 | 實際除權息日 | ✅ 股東會後即公告，事先數週已知 |
| 減資 | 實際減資日 | ✅ 同上 |

## 特徵

    days_since_revenue   距上次營收公布的交易日數（上限 30）
    days_to_revenue      距下次營收法定截止日的日曆日數（上限 30）
    revenue_window       是否落在營收公布前後 ±2 日
    days_since_exdiv     距上次除權息／減資的日數（上限 60）
    days_to_exdiv        距下次除權息／減資的日數（上限 60）
    exdiv_window         是否落在除權息前後 ±2 日
    event_density        近 10 日內發生的事件數
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

EVENT_FEATURES = [
    'days_since_revenue', 'days_to_revenue', 'revenue_window',
    'days_since_exdiv', 'days_to_exdiv', 'exdiv_window',
    'event_density',
]

CAP_REVENUE = 30      # 距離超過此天數即截斷（再遠就沒有意義）
CAP_EXDIV = 60

EXDIV_SQL = """
    SELECT stock_id, ex_date FROM stock_dividend_result
    UNION ALL
    SELECT stock_id, ex_date FROM stock_capital_reduction
"""

REVENUE_DAY = 10      # 台股月營收法定公布截止日


def _load_exdiv():
    from db.connection import get_conn
    try:
        with get_conn() as conn:
            exd = pd.read_sql(EXDIV_SQL, conn)
    except Exception as e:
        logger.warning('[event] 讀取除權息資料失敗，該類特徵停用：%s', e)
        return pd.DataFrame()
    if not exd.empty:
        exd['ex_date'] = pd.to_datetime(exd['ex_date'])
    return exd


def _revenue_marks(dates: pd.Series):
    """
    回傳 (上一個營收公布日, 下一個營收公布日)，皆以每月 10 日為準。
    由法規決定，任何時點都事先可知，不構成洩漏。
    """
    d = pd.to_datetime(dates)
    month_start = d.values.astype('datetime64[M]')
    this_10 = pd.to_datetime(month_start + np.timedelta64(REVENUE_DAY - 1, 'D'))
    prev_10 = pd.to_datetime(
        (month_start - np.timedelta64(1, 'M')).astype('datetime64[M]')
        + np.timedelta64(REVENUE_DAY - 1, 'D'))
    next_10 = pd.to_datetime(
        (month_start + np.timedelta64(1, 'M')).astype('datetime64[M]')
        + np.timedelta64(REVENUE_DAY - 1, 'D'))

    before = d <= this_10
    last_mark = pd.Series(np.where(before, prev_10, this_10), index=d.index)
    next_mark = pd.Series(np.where(before, this_10, next_10), index=d.index)
    return last_mark, next_mark


def add_event_features(panel: pd.DataFrame) -> pd.DataFrame:
    """在面板上加計事件特徵；事件資料缺漏時填中性值（不會讓管線失效）。"""
    p = panel.copy()
    p['trade_date'] = pd.to_datetime(p['trade_date'])
    exd = _load_exdiv()

    # 預設中性值：視為「距離事件很遠」
    p['days_since_exdiv'] = CAP_EXDIV
    p['days_to_exdiv'] = CAP_EXDIV
    p['exdiv_window'] = 0

    # ── 營收：以法規排程（每月 10 日）為事件日 ──────────────────────────
    last_rev, next_rev = _revenue_marks(p['trade_date'])
    p['days_since_revenue'] = ((p['trade_date'] - last_rev).dt.days
                               .clip(0, CAP_REVENUE).values)
    p['days_to_revenue'] = ((next_rev - p['trade_date']).dt.days
                            .clip(0, CAP_REVENUE).values)
    p['revenue_window'] = ((p['days_since_revenue'] <= 2) |
                           (p['days_to_revenue'] <= 2)).astype(int)

    # ── 除權息／減資：事先公告，前後皆可用實際日期 ──────────────────────
    if not exd.empty:
        left = p[['stock_id', 'trade_date']].sort_values('trade_date')
        back = pd.merge_asof(left, exd.sort_values('ex_date'),
                             left_on='trade_date', right_on='ex_date',
                             by='stock_id', direction='backward')
        fwd = pd.merge_asof(left, exd.sort_values('ex_date'),
                            left_on='trade_date', right_on='ex_date',
                            by='stock_id', direction='forward')
        since = (back['trade_date'] - back['ex_date']).dt.days
        to = (fwd['ex_date'] - fwd['trade_date']).dt.days
        p['days_since_exdiv'] = since.fillna(CAP_EXDIV).clip(0, CAP_EXDIV).values
        p['days_to_exdiv'] = to.fillna(CAP_EXDIV).clip(0, CAP_EXDIV).values
        p['exdiv_window'] = ((p['days_since_exdiv'] <= 2) |
                             (p['days_to_exdiv'] <= 2)).astype(int)

    p['event_density'] = ((p['days_since_revenue'] <= 10).astype(int) +
                          (p['days_since_exdiv'] <= 10).astype(int) +
                          (p['days_to_exdiv'] <= 10).astype(int))

    n_rev_win = int(p['revenue_window'].sum())
    n_div_win = int(p['exdiv_window'].sum())
    logger.info('[event] 營收視窗 %d 筆、除權息視窗 %d 筆（共 %d 筆）',
                n_rev_win, n_div_win, len(p))
    return p
