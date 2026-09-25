"""
台指期夜盤特徵（Iteration 28）
──────────────────────────────
夜盤（15:00~翌日 05:00）是市場在台股開盤前對次日的**直接定價**。
探測結果（`probe_night_session.py`，2024-01 起 14,880 筆）：

    夜盤隱含隔夜變動 vs 個股開盤跳空   相關 +0.567
    費半 SOXX 隔夜   vs 個股開盤跳空   相關 +0.483
    R²：只用夜盤 0.3215、只用費半 0.2336、兩者一起 0.3319

亦即**夜盤幾乎吃掉美股的全部資訊**（美股額外只貢獻 +0.0104），
反過來卻不成立（夜盤額外貢獻 +0.0983）。

## 時序：搞反就是未來資訊洩漏

`futures_daily` 裡 `after_market` 那一列的收盤價，幾乎等於**同一個 trade_date**
的日盤開盤價（中位數差 0.185%）——它領先同日開盤。所以要預測 D 日的開盤跳空，
用的是 **D 日那列的 after_market**，而不是 D-1 的。

反過來，`position`（日盤）那列是 D 日 09:00~13:30 的結果，**不能**用來預測
同一天的開盤——那是事後資料。所以本模組的規則是：

    可用：D 日 after_market 的一切，加上 D-1（含）以前的所有資料
    禁用：D 日 position 的任何欄位

## 為什麼還保留量能特徵

夜盤成交量相對日盤的比例，反映「隔夜有多少人急著反應」。
量縮的夜盤價格代表性差，模型應該有機會學到「這時候別太相信夜盤價位」。
這是假設，不是量測結論——消融實驗會告訴我們它有沒有用。
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

NIGHT_FEATURES = [
    'night_ret',        # 夜盤收盤 ÷ 前一日日盤收盤 − 1：隔夜隱含變動（核心特徵）
    'night_range',      # 夜盤高低差 ÷ 前一日日盤收盤：隔夜的分歧程度
    'night_pos',        # 夜盤收盤在其高低區間的位置（0=最低、1=最高）
    'night_open_ret',   # 夜盤開盤跳空：15:00 一開盤就反應多少
    'night_drift',      # 夜盤收盤 ÷ 夜盤開盤 − 1：整段夜盤的走勢
    'night_vol_ratio',  # 夜盤量 ÷ 前 20 日夜盤量均值：這晚有多少人在動
    'night_vs_day_vol', # 夜盤量 ÷ 前一日日盤量：相對規模
    'night_ret_ma3',    # 近三日夜盤變動均值：連續性
]

LOAD_SQL = """
    SELECT futures_id, trade_date, session,
           open_price, high_price, low_price, close_price, volume
      FROM futures_daily
     WHERE futures_id = %s AND close_price > 0
     ORDER BY trade_date, session
"""


def load_night_panel(futures_id: str = 'TX') -> pd.DataFrame:
    """
    回傳以 trade_date 為索引的夜盤特徵表。

    只用 after_market 的價量，加上**前一日**的日盤收盤與成交量當基準——
    當日日盤的任何欄位都不能碰，那是開盤之後才知道的事。
    """
    from db.connection import get_conn
    with get_conn() as conn:
        raw = pd.read_sql(LOAD_SQL, conn, params=(futures_id,))
    if raw.empty:
        logger.warning('[night] %s 無資料', futures_id)
        return pd.DataFrame()

    raw['trade_date'] = pd.to_datetime(raw['trade_date'])
    piv = raw.pivot(index='trade_date', columns='session').sort_index()

    def col(field, session):
        try:
            return piv[(field, session)].astype(float)
        except KeyError:
            return pd.Series(np.nan, index=piv.index)

    n_open, n_high = col('open_price', 'after_market'), col('high_price', 'after_market')
    n_low, n_close = col('low_price', 'after_market'), col('close_price', 'after_market')
    n_vol = col('volume', 'after_market')
    d_close, d_vol = col('close_price', 'position'), col('volume', 'position')

    # 基準一律是「前一日」的日盤——當日日盤還沒發生
    prev_close = d_close.shift(1)
    prev_vol = d_vol.shift(1)

    out = pd.DataFrame(index=piv.index)
    out['night_ret'] = n_close / prev_close - 1
    out['night_range'] = (n_high - n_low) / prev_close
    rng = (n_high - n_low).replace(0, np.nan)
    out['night_pos'] = (n_close - n_low) / rng
    out['night_open_ret'] = n_open / prev_close - 1
    out['night_drift'] = n_close / n_open.replace(0, np.nan) - 1
    out['night_vol_ratio'] = n_vol / n_vol.rolling(20, min_periods=5).mean().shift(1)
    out['night_vs_day_vol'] = n_vol / prev_vol.replace(0, np.nan)
    out['night_ret_ma3'] = out['night_ret'].rolling(3, min_periods=2).mean()

    # 極端值多半是契約轉倉或無效報價造成的，留著會主導樹模型的分裂點
    for c in ('night_ret', 'night_open_ret', 'night_drift'):
        out.loc[out[c].abs() > 0.15, c] = np.nan
    out = out.replace([np.inf, -np.inf], np.nan)

    logger.info('[night] %s 夜盤特徵 %d 個交易日（%s ~ %s）', futures_id, len(out),
                str(out.index.min())[:10], str(out.index.max())[:10])
    return out.reset_index()


def attach(panel: pd.DataFrame, futures_id: str = 'TX',
           date_col: str = 'trade_date') -> pd.DataFrame:
    """
    把夜盤特徵併到個股面板上（同一個 trade_date 直接對應）。

    用 inner-merge 的日期對齊即可，不需要 as-of：夜盤與台股是同一個交易日曆，
    每個台股交易日都有對應的那一段夜盤。
    """
    night = load_night_panel(futures_id)
    if night.empty:
        return panel
    p = panel.copy()
    p[date_col] = pd.to_datetime(p[date_col])
    return p.merge(night, left_on=date_col, right_on='trade_date',
                   how='left', suffixes=('', '_night'))
