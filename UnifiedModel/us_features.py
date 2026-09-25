"""
美股隔夜特徵（Iteration 14）
────────────────────────────
台股在美股收盤後開盤，**隔夜美股走勢是台股次日的領先資訊**，
而先前的模型完全沒有這項輸入。半導體類股與台灣電子股的連動尤其直接。

## 時序對齊（最容易寫錯、也最致命的一步）

台股 T 日 09:00 開盤（台灣時間），美股 T−1 日 16:00 ET 收盤
＝台灣時間 T 日 04:00 —— 所以台股 T 日**看得到**美股 T−1 日收盤。
但美股 T 日收盤在台股 T 日收盤**之後**，用它就是洩漏未來資訊。

因此合併條件必須是 `美股日期 < 台股日期`（嚴格小於），
以 `merge_asof(..., allow_exact_matches=False)` 實作。
若寫成 `<=`，在兩地同為交易日時就會用到當天的美股收盤 —— 那是未來資料。

## 報酬率一律用 adj_close

原始 close 在分割與配息日會出現假跳空（例如 NVDA 多次分割），
模型會把它當成真實的暴漲暴跌來學。
"""

import numpy as np
import pandas as pd

# 每個標的都要有明確的預期作用
US_TICKERS = {
    'SPY':  'mkt',    # 美股大盤情緒
    'QQQ':  'tech',   # 科技股情緒
    'SOXX': 'semi',   # 費城半導體 ETF —— 與台灣電子股連動最直接
    'NVDA': 'semi',
    'AMD':  'semi',
    'MU':   'semi',   # 記憶體，對應旺宏／華邦電
    'TSM':  'adr',    # 台積電 ADR，對應 2330
    'UMC':  'adr',    # 聯電 ADR，對應 2303
}

US_FEATURES = [
    'us_spy_ret1', 'us_spy_ret5', 'us_spy_vol20',
    'us_qqq_ret1', 'us_qqq_ret5',
    'us_soxx_ret1', 'us_soxx_ret5', 'us_soxx_vol20',
    'us_nvda_ret1', 'us_amd_ret1', 'us_mu_ret1',
    'us_tsm_ret1', 'us_tsm_ret5', 'us_umc_ret1',
    'us_semi_breadth',    # 半導體股上漲家數比例
    'us_risk_on',         # QQQ 相對 SPY 的超額（科技股風險偏好）
    'us_gap_days',        # 距離最近一個美股交易日的天數（連假時資訊較舊）
]

LOAD_US_SQL = """
    SELECT ticker, trade_date, adj_close, close_price, volume
    FROM us_daily_prices
    WHERE adj_close > 0
    ORDER BY ticker, trade_date
"""


def build_us_daily(raw_us: pd.DataFrame) -> pd.DataFrame:
    """把美股長表轉成「一列一個美股交易日」的特徵表。"""
    df = raw_us.copy()
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df['adj_close'] = pd.to_numeric(df['adj_close'], errors='coerce')

    wide = df.pivot_table(index='trade_date', columns='ticker',
                          values='adj_close', aggfunc='last').sort_index()

    out = pd.DataFrame(index=wide.index)
    for tk in US_TICKERS:
        if tk not in wide.columns:
            continue
        s = wide[tk]
        r1 = s.pct_change()
        low = tk.lower()
        out[f'us_{low}_ret1'] = r1
        out[f'us_{low}_ret5'] = s.pct_change(5)
        if tk in ('SPY', 'SOXX'):
            out[f'us_{low}_vol20'] = r1.rolling(20).std()

    semis = [f'us_{t.lower()}_ret1' for t in ('SOXX', 'NVDA', 'AMD', 'MU')
             if f'us_{t.lower()}_ret1' in out.columns]
    out['us_semi_breadth'] = (out[semis] > 0).mean(axis=1) if semis else np.nan
    if 'us_qqq_ret1' in out and 'us_spy_ret1' in out:
        out['us_risk_on'] = out['us_qqq_ret1'] - out['us_spy_ret1']

    out = out.reset_index().rename(columns={'trade_date': 'us_date'})
    return out


def attach_us_features(panel: pd.DataFrame, us_daily: pd.DataFrame) -> pd.DataFrame:
    """
    把美股特徵接到台股面板上。

    **嚴格以「美股日期 < 台股日期」對齊**（allow_exact_matches=False），
    確保只用到台股開盤前已經公布的美股收盤。
    """
    p = panel.copy()
    p['trade_date'] = pd.to_datetime(p['trade_date'])
    u = us_daily.sort_values('us_date').copy()

    tw_dates = pd.DataFrame({'trade_date': np.sort(p['trade_date'].unique())})
    mapped = pd.merge_asof(
        tw_dates, u,
        left_on='trade_date', right_on='us_date',
        direction='backward',
        allow_exact_matches=False,   # ← 關鍵：同日的美股收盤是未來資訊
    )
    mapped['us_gap_days'] = (mapped['trade_date'] - mapped['us_date']).dt.days

    merged = p.merge(mapped.drop(columns=['us_date']), on='trade_date', how='left')
    return merged


def load_and_attach(panel: pd.DataFrame) -> pd.DataFrame:
    """便利入口：讀 DB 的美股資料並接到面板上。"""
    from db.connection import get_conn
    with get_conn() as conn:
        raw_us = pd.read_sql(LOAD_US_SQL, conn)
    if raw_us.empty:
        return panel
    return attach_us_features(panel, build_us_daily(raw_us))
