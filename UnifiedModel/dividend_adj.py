"""
除權息調整（Iteration 17）
──────────────────────────
共用模組：把「除權息日的機械性價格缺口」從報酬率計算中扣除。

為何重要——實測 24 檔 479 筆除權息事件的機械性缺口：

    配息（息）    平均 3.57%
    配股+配息     平均 8.91%
    除權息        平均 11.63%
    極端案例      −20.83%（2352 於 2003-06-23）

這些缺口與市場走勢無關，卻會：
  · 讓跳空模型把它當成真實跳空學習
  · 讓波動度特徵嚴重灌水——單一 20% 的假跌幅落在 20 日滾動窗內，
    會把該股的波動率估計推高數倍，且影響持續 20 個交易日

正確作法是以交易所計算的**除權息參考價**取代前一日收盤，
`stock_dividend_result.reference_price` 即為此值。

註：本專案的台股資料表存的是**未調整**價格（FinMind taiwan_stock_daily 的 close），
    這與美股表使用 adj_close 的作法不同，故台股需要這層額外處理。
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DIVIDEND_SQL = """
    SELECT stock_id, ex_date, reference_price
    FROM stock_dividend_result
    WHERE reference_price > 0
"""


def load_dividends() -> pd.DataFrame:
    """讀取除權息參考價；表不存在或無資料時回傳空表（呼叫端自動跳過調整）。"""
    try:
        from db.connection import get_conn
        with get_conn() as conn:
            div = pd.read_sql(DIVIDEND_SQL, conn)
        if div.empty:
            return div
        div['ex_date'] = pd.to_datetime(div['ex_date'])
        return div
    except Exception as e:
        logger.warning('[dividend_adj] 讀取除權息資料失敗，略過調整：%s', e)
        return pd.DataFrame()


def adjusted_prev_close(panel: pd.DataFrame,
                        date_col: str = 'trade_date',
                        close_col: str = 'close') -> pd.Series:
    """
    回傳「調整後的前一日收盤」序列，可直接用來算報酬率或跳空。

    除權息日 → 除權息參考價；其餘日 → 前一日收盤。
    panel 需含 stock_id 與日期、收盤欄位，且已依股票與日期排序。
    """
    p = panel.copy()
    p[date_col] = pd.to_datetime(p[date_col])
    prev = p.groupby('stock_id')[close_col].shift(1)

    div = load_dividends()
    if div.empty:
        return prev

    merged = p[['stock_id', date_col]].merge(
        div, left_on=['stock_id', date_col],
        right_on=['stock_id', 'ex_date'], how='left')
    ref = merged['reference_price'].values
    n_adj = int(pd.notna(ref).sum())
    if n_adj:
        logger.info('[dividend_adj] 調整 %d 筆除權息日的基準價', n_adj)
    return pd.Series(np.where(pd.notna(ref), ref, prev.values), index=p.index)


def adjusted_returns(panel: pd.DataFrame,
                     date_col: str = 'trade_date',
                     close_col: str = 'close') -> pd.Series:
    """
    除權息與減資調整後的日報酬率。

    Iteration 18 起，`stock_daily_prices.adj_close` 已預先還原全部公司行動，
    面板若含該欄位就直接用它（最快也最完整——涵蓋減資，
    而本模組原本的查表法只處理除權息）。
    缺欄位時才退回原本的「以參考價取代前一日收盤」邏輯。
    """
    if 'adj_close' in panel.columns and panel['adj_close'].notna().any():
        return panel.groupby('stock_id')['adj_close'].transform(
            lambda s: s.pct_change())
    prev = adjusted_prev_close(panel, date_col, close_col)
    return panel[close_col] / prev - 1
