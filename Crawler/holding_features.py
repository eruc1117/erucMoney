"""
外資真實持股特徵（Iteration 36）
──────────────────────────────
Iteration 35 把證交所揭露的外資持股（`stock_foreign_holding`）補進資料庫，
26 檔自 2012-05 起全部齊全。在那之前 `features.py` 的 `holding_chg_5d` 一直被排除，
因為 `stock_chip_analysis.foreign_holding_ratio` 從未被填入，留著會讓 dropna 清空整張表。

現在資料在了，問題變成：**它有沒有模型用得上的資訊？**

## 與買賣超的差別

三大法人買賣超（chip 區塊）是**流量**：今天外資淨買了多少。
持股是**存量**：外資手上現在有多少、佔已發行股數幾成。

兩者的日變動高度相關（2330 近期：買超 +603 萬股，持股 +335 萬股），
但不相等——借券、鉅額交易、非集中市場的移轉都會讓持股變動偏離買賣超。
更重要的是存量本身帶有流量沒有的資訊：

  · 水位：外資持股 69% 與 9% 的股票，同樣被買超 1 萬張的意義不同
  · 長期趨勢：60 日的持股變化，等於把買賣超累積後再扣掉非市場移轉
  · 上限距離：外資投資上限（多數 100%，少數產業有法定上限）扣掉持股

這些是不是有用，得靠巢狀走查（`UnifiedModel/optimise_all.py`）決定，
不是加了就上。本模組只負責把特徵算對。

## 時序

持股統計揭露 D 日收盤後的持股，與 D 日的三大法人買賣超同一時點可得。
所以 D 日那列的持股特徵可用於預測 D+1 起的事，與 chip 區塊口徑一致。
線上偶爾持股比行情晚一天揭露，as-of 合併會退回前一日的持股；
對存量特徵而言，一天的延遲影響遠小於缺列。
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

HOLDING_FEATURES = [
    'fh_ratio',      # 外資持股比例（0~1）：水位
    'fh_chg_1d',     # 持股比例日變動（百分點）
    'fh_chg_5d',     # 5 日變動：與 foreign_5d 對照，多出非市場移轉的部分
    'fh_chg_20d',    # 20 日變動：中期趨勢
    'fh_chg_60d',    # 60 日變動：長期趨勢，這是買賣超特徵沒有的視野
    'fh_z60',        # 持股比例相對自身 60 日均值的 z 分數：現在偏高還是偏低
    'fh_headroom',   # 外資投資上限 − 持股（0~1）：還能買多少
]

LOAD_SQL = """
    SELECT stock_id, trade_date, foreign_ratio, foreign_upper_limit_ratio
      FROM stock_foreign_holding
     WHERE foreign_ratio IS NOT NULL
     ORDER BY stock_id, trade_date
"""


def load_holding() -> pd.DataFrame:
    """回傳每檔每日的外資持股比例與上限（尚未算特徵）。"""
    from db.connection import get_conn
    with get_conn() as conn:
        raw = pd.read_sql(LOAD_SQL, conn)
    if raw.empty:
        logger.warning('[holding] stock_foreign_holding 無資料')
        return raw
    raw['trade_date'] = pd.to_datetime(raw['trade_date'])
    raw['stock_id'] = raw['stock_id'].astype(str).str.strip()
    for c in ('foreign_ratio', 'foreign_upper_limit_ratio'):
        raw[c] = pd.to_numeric(raw[c], errors='coerce')
    return raw


def _features_one(g: pd.DataFrame) -> pd.DataFrame:
    """單一股票：以持股表自己的日曆算特徵，再由呼叫端 as-of 併到面板。"""
    g = g.sort_values('trade_date').copy()
    ratio = g['foreign_ratio']                       # 百分比（0~100）
    g['fh_ratio'] = ratio / 100.0
    for n in (1, 5, 20, 60):
        g[f'fh_chg_{n}d'] = ratio.diff(n)
    ma60 = ratio.rolling(60, min_periods=40).mean()
    sd60 = ratio.rolling(60, min_periods=40).std()
    g['fh_z60'] = (ratio - ma60) / (sd60 + 1e-6)
    upper = g['foreign_upper_limit_ratio'].fillna(100.0)
    g['fh_headroom'] = (upper - ratio).clip(lower=0) / 100.0
    return g


def build_holding_features() -> pd.DataFrame:
    """每檔每日的持股特徵表（stock_id, trade_date, fh_*）。"""
    raw = load_holding()
    if raw.empty:
        return raw
    out = pd.concat([_features_one(g) for _, g in raw.groupby('stock_id')],
                    ignore_index=True)
    logger.info('[holding] %d 檔 %d 列，%s ~ %s', out['stock_id'].nunique(), len(out),
                str(out['trade_date'].min())[:10], str(out['trade_date'].max())[:10])
    return out[['stock_id', 'trade_date'] + HOLDING_FEATURES]


def attach(panel: pd.DataFrame, date_col: str = 'trade_date') -> pd.DataFrame:
    """
    併到台股面板。逐檔 as-of（backward、允許同日）：
    持股表偶有缺日（例如揭露延遲），硬對齊會掉樣本；退回前一日的存量是合理的。

    面板若含持股表沒有的股票（例如美股代號），該列的 fh_* 為 NaN，
    由呼叫端的 align/dropna 處理——不在這裡補零，補零就是捏造持股。
    """
    hold = build_holding_features()
    if hold.empty:
        return panel
    p = panel.copy()
    p[date_col] = pd.to_datetime(p[date_col])
    p['_sid'] = p['stock_id'].astype(str).str.strip()
    hold = hold.rename(columns={'stock_id': '_sid', 'trade_date': '_hdate'})
    merged = pd.merge_asof(
        p.sort_values(date_col), hold.sort_values('_hdate'),
        left_on=date_col, right_on='_hdate', by='_sid',
        direction='backward', allow_exact_matches=True,
        tolerance=pd.Timedelta(days=10))
    return merged.drop(columns=['_sid', '_hdate'])
