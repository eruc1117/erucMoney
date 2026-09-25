"""
亞洲鄰近市場特徵：韓股 KOSPI、日股 Nikkei（Iteration 29）
──────────────────────────────────────────────────────
## 時序才是重點，不是特徵本身

韓日比台股早一小時開盤，這是它們有價值的唯一理由；也正因為只早一小時，
**收盤資料反而不能用**。三種欄位的可用性完全不同：

| 欄位 | 何時知道（台北時間） | 預測台股當日開盤 | 預測台股當日收盤 |
|------|-------------------|----------------|----------------|
| 當日開盤價 | 08:00 | **可用** | **可用** |
| 前一日收盤價 | 前一日 14:00~14:30 | **可用** | **可用** |
| 當日收盤價 | 14:00~14:30 | 洩漏 | 洩漏（台股 13:30 已收） |

本模組**只產出前兩類**。當日收盤價一律不碰——不是保守，是那個數字在做預測時
根本還不存在。這種錯誤的症狀是「模型好得不像話」，而且不會有任何報錯。

## 前一日收盤為什麼仍有增量資訊

台股 13:30 收盤，韓國 14:30、日本 14:00 才收。所以韓日的前一日收盤
比台股自己的前一日收盤**多含約一小時的市場反應**。這段差異不大，但存在。

## 為什麼開盤價這一欄最值得期待

韓日開盤（08:00 台北）已經把整個美股隔夜消化過一輪，而且是**亞洲時區的參與者**
在消化。它比美股原始報酬更接近「亞洲市場今天怎麼看」，理論上對台股開盤更有指示性。
是否真的如此由消融實驗決定，不由這段話決定。
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

SYMBOLS = {'^KS11': 'kr', '^N225': 'jp'}

# 只有這些欄位在台股開盤前拿得到
INTL_FEATURES = [
    'kr_open_ret',    # 韓股今日開盤 ÷ 韓股昨收 − 1：亞洲時區對美股隔夜的第一反應
    'kr_prev_ret',    # 韓股昨日收盤報酬（含台股收盤後那一小時）
    'jp_open_ret',    # 日股今日開盤跳空
    'jp_prev_ret',    # 日股昨日收盤報酬
    'asia_open_ret',  # 韓日開盤跳空平均：兩個市場一致時訊號較強
    'asia_open_gap',  # 韓日開盤跳空之差：兩者分歧代表區域訊號不明確
    'kr_prev_vol10',  # 韓股近 10 日報酬波動：區域風險情緒
]

LOAD_SQL = """
    SELECT symbol, trade_date, open_price, close_price
      FROM index_daily_prices
     WHERE close_price > 0 AND open_price > 0
     ORDER BY symbol, trade_date
"""


def load_intl_daily() -> pd.DataFrame:
    """回傳以 trade_date 為鍵的韓日特徵表（只含台股開盤前可得的欄位）。"""
    from db.connection import get_conn
    with get_conn() as conn:
        raw = pd.read_sql(LOAD_SQL, conn)
    if raw.empty:
        logger.warning('[intl] 無韓日指數資料')
        return pd.DataFrame()

    raw['trade_date'] = pd.to_datetime(raw['trade_date'])
    out = None
    for sym, tag in SYMBOLS.items():
        d = raw[raw['symbol'] == sym].sort_values('trade_date').copy()
        if d.empty:
            continue
        prev_close = d['close_price'].shift(1)
        f = pd.DataFrame({'trade_date': d['trade_date'].values})
        # 當日開盤相對昨收：這是台股開盤前唯一「今天」的資訊
        f[f'{tag}_open_ret'] = (d['open_price'] / prev_close - 1).values
        # 昨日收盤報酬：昨收 ÷ 前天收，全部是過去資料
        f[f'{tag}_prev_ret'] = (prev_close / d['close_price'].shift(2) - 1).values
        if tag == 'kr':
            f['kr_prev_vol10'] = (
                (d['close_price'].pct_change().shift(1)
                 .rolling(10, min_periods=5).std()).values)
        out = f if out is None else out.merge(f, on='trade_date', how='outer')

    if out is None:
        return pd.DataFrame()

    out = out.sort_values('trade_date').reset_index(drop=True)
    if {'kr_open_ret', 'jp_open_ret'}.issubset(out.columns):
        out['asia_open_ret'] = out[['kr_open_ret', 'jp_open_ret']].mean(axis=1)
        out['asia_open_gap'] = (out['kr_open_ret'] - out['jp_open_ret']).abs()

    # 指數偶有異常報價（休市補值、換算錯誤），10% 以上的開盤跳空幾乎都是那類
    for c in ('kr_open_ret', 'jp_open_ret', 'kr_prev_ret', 'jp_prev_ret'):
        if c in out.columns:
            out.loc[out[c].abs() > 0.10, c] = np.nan
    out = out.replace([np.inf, -np.inf], np.nan)

    logger.info('[intl] 韓日特徵 %d 個交易日（%s ~ %s）', len(out),
                str(out['trade_date'].min())[:10], str(out['trade_date'].max())[:10])
    return out


def attach(panel: pd.DataFrame, date_col: str = 'trade_date') -> pd.DataFrame:
    """
    併到台股面板上。用 as-of（backward、允許同日）而不是 inner-join：
    韓日與台灣的休市日不同，硬對齊會在連假前後大量掉樣本。
    允許同日是正確的——當日開盤價在台股開盤前就有了。
    """
    intl = load_intl_daily()
    if intl.empty:
        return panel
    p = panel.copy()
    p[date_col] = pd.to_datetime(p[date_col])
    merged = pd.merge_asof(
        p.sort_values(date_col), intl.sort_values('trade_date'),
        left_on=date_col, right_on='trade_date',
        direction='backward', allow_exact_matches=True, suffixes=('', '_intl'))
    return merged
