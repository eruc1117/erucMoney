"""
整合特徵工程（Iteration 12）
────────────────────────────
把專案目前**所有可用資料源**放進同一張特徵表：

  價量技術面  OHLCV、成交金額、成交筆數 → 動能／波動／RSI／MACD／布林／量價背離
  籌碼面      三大法人買賣超、外資持股比 → 多天期累計、連續性、法人一致性
  橫斷面      當日 22 檔之間的百分位排名 → 「只有這檔被買超」vs「全體都被買超」
  大盤情境    全體平均報酬、漲家數比例、市場波動 → регime 判斷

設計原則（沿用 Iteration 9 的教訓）：
  · 所有特徵只用「當日（含）以前」的資料，無未來洩漏
  · 橫斷面特徵只用同日同儕資訊，不跨日
  · 訓練與推論共用本模組，避免兩邊定義不一致
"""

import numpy as np
import pandas as pd

# ── 特徵分組（便於做消融實驗）──────────────────────────────────────────────
PRICE_FEATURES = [
    'ret_1d', 'ret_3d', 'ret_5d', 'ret_10d', 'ret_20d',
    'vol_5d', 'vol_10d', 'vol_20d',
    'rsi_14', 'macd_hist', 'bb_pos', 'atr_pct',
    'ma5_dev', 'ma20_dev', 'ma60_dev',
    'hl_pos', 'gap_pct', 'body_ratio',
    'vol_ratio', 'vol_trend', 'turnover_ratio', 'avg_trade_size_ratio',
    'up_days_5', 'up_days_10',
]

CHIP_FEATURES = [
    'foreign_1d', 'trust_1d', 'dealer_1d', 'total_1d',
    'foreign_3d', 'trust_3d', 'total_3d',
    'foreign_5d', 'trust_5d', 'total_5d',
    'foreign_10d', 'total_10d',
    'buy_days_5', 'foreign_buy_days_5', 'foreign_buy_days_10',
    'align_foreign_trust', 'chip_momentum',
    # 註：外資持股比（holding_chg_5d）仍排除。原因有兩段：
    #   · Iteration 12~35：`stock_chip_analysis.foreign_holding_ratio` 100% NULL，留著會清空整張表。
    #   · Iteration 36：真實持股已進 `stock_foreign_holding`，做成獨立區塊
    #     （`Crawler/holding_features.py`，panel 的 'holding'）用巢狀走查測過——
    #     跳空／振幅／波動率／成交量四個模型 12 折中只被選中 1 折，M3 消融方向 −0.37pp，
    #     全部未通過。資料在，但沒有增量資訊，所以不進 CHIP_FEATURES。
]

CS_FEATURES = [
    'cs_ret_5d', 'cs_ret_20d', 'cs_foreign_5d', 'cs_total_5d',
    'cs_vol_ratio', 'cs_rsi', 'cs_vol_20d',
]

MARKET_FEATURES = [
    'mkt_ret_1d', 'mkt_ret_5d', 'mkt_breadth', 'mkt_vol_20d', 'mkt_chip_breadth',
]

ALL_FEATURES = PRICE_FEATURES + CHIP_FEATURES + CS_FEATURES + MARKET_FEATURES

MIN_HISTORY = 65      # 需要 60 日均線 + 緩衝


# ── 個股特徵 ────────────────────────────────────────────────────────────────
def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = (-delta.clip(upper=0)).rolling(n).mean()
    rs = gain / (loss + 1e-9)
    return 100 - 100 / (1 + rs)


def build_stock_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    單一股票的價量 + 籌碼特徵。
    df 需含：trade_date, open, high, low, close, volume, turnover, trades,
             foreign_net, trust_net, dealer_net, total_net, holding_ratio
    """
    d = df.sort_values('trade_date').reset_index(drop=True).copy()
    for c in ('open', 'high', 'low', 'close', 'adj_close', 'volume', 'turnover',
              'trades', 'foreign_net', 'trust_net', 'dealer_net', 'total_net',
              'holding_ratio'):
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors='coerce')
    d[['foreign_net', 'trust_net', 'dealer_net', 'total_net']] = \
        d[['foreign_net', 'trust_net', 'dealer_net', 'total_net']].fillna(0.0)

    close, high, low = d['close'], d['high'], d['low']
    # **報酬與均線一律以 adj_close 計算**（Iteration 18）：
    # 原始 close 在除權息與減資日會出現機械性缺口，實測減資日曾有 +123% 的
    # 假漲幅（2337 於 2017-08-28），足以摧毀其後 20 日的波動度估計。
    adj = d['adj_close'] if 'adj_close' in d.columns else close
    ret1 = adj.pct_change()

    # ── 動能 ────────────────────────────────────────────────────────────
    d['ret_1d'] = ret1
    for n in (3, 5, 10, 20):
        d[f'ret_{n}d'] = adj.pct_change(n)

    # ── 波動 ────────────────────────────────────────────────────────────
    for n in (5, 10, 20):
        d[f'vol_{n}d'] = ret1.rolling(n).std()

    # ── 技術指標 ────────────────────────────────────────────────────────
    d['rsi_14'] = _rsi(adj, 14) / 100.0
    ema12, ema26 = adj.ewm(span=12).mean(), adj.ewm(span=26).mean()
    macd = ema12 - ema26
    d['macd_hist'] = (macd - macd.ewm(span=9).mean()) / (adj + 1e-9)

    ma20 = adj.rolling(20).mean()
    sd20 = adj.rolling(20).std()
    d['bb_pos'] = (adj - ma20) / (2 * sd20 + 1e-9)        # 布林通道相對位置

    tr = pd.concat([high - low,
                    (high - close.shift()).abs(),
                    (low - close.shift()).abs()], axis=1).max(axis=1)
    d['atr_pct'] = tr.rolling(14).mean() / (close + 1e-9)

    for n in (5, 20, 60):
        d[f'ma{n}_dev'] = adj / (adj.rolling(n).mean() + 1e-9) - 1

    # ── 當日型態 ────────────────────────────────────────────────────────
    d['hl_pos'] = (close - low) / (high - low + 1e-9)         # 收在當日高低點何處
    d['gap_pct'] = (d['open'] - close.shift()) / (close.shift() + 1e-9)
    d['body_ratio'] = (close - d['open']).abs() / (high - low + 1e-9)

    # ── 量能 ────────────────────────────────────────────────────────────
    vol20 = d['volume'].rolling(20, min_periods=10).mean()
    d['vol_ratio'] = d['volume'] / (vol20 + 1e-9)
    d['vol_trend'] = (d['volume'].rolling(5).mean() /
                      (d['volume'].rolling(20).mean() + 1e-9))
    d['turnover_ratio'] = d['turnover'] / (d['turnover'].rolling(20).mean() + 1e-9)
    avg_size = d['turnover'] / (d['trades'] + 1e-9)           # 每筆平均金額≈大單比重
    d['avg_trade_size_ratio'] = avg_size / (avg_size.rolling(20).mean() + 1e-9)

    d['up_days_5'] = (ret1 > 0).rolling(5).sum()
    d['up_days_10'] = (ret1 > 0).rolling(10).sum()

    # ── 籌碼（以 20 日均量標準化，使跨股票可比）─────────────────────────
    for col, name in (('foreign_net', 'foreign'), ('trust_net', 'trust'),
                      ('dealer_net', 'dealer'), ('total_net', 'total')):
        d[f'{name}_1d'] = d[col] / (vol20 + 1e-9)
    for n in (3, 5, 10):
        for col, name in (('foreign_net', 'foreign'), ('trust_net', 'trust'),
                          ('total_net', 'total')):
            if name == 'trust' and n == 10:
                continue
            d[f'{name}_{n}d'] = d[col].rolling(n).sum() / (vol20 + 1e-9)

    d['buy_days_5'] = (d['total_net'] > 0).rolling(5).sum()
    d['foreign_buy_days_5'] = (d['foreign_net'] > 0).rolling(5).sum()
    d['foreign_buy_days_10'] = (d['foreign_net'] > 0).rolling(10).sum()

    f5 = d['foreign_net'].rolling(5).sum()
    t5 = d['trust_net'].rolling(5).sum()
    d['align_foreign_trust'] = np.sign(f5) * np.sign(t5)
    # 籌碼動能：近 5 日買超 vs 前 5 日買超（法人態度是否轉向）
    d['chip_momentum'] = (f5 - d['foreign_net'].shift(5).rolling(5).sum()) / (vol20 + 1e-9)
    d['holding_chg_5d'] = d['holding_ratio'].diff(5)

    return d


# ── 橫斷面與大盤 ────────────────────────────────────────────────────────────
def add_cross_sectional(panel: pd.DataFrame) -> pd.DataFrame:
    """在多股票面板上加計同日橫斷面排名與大盤情境特徵。"""
    p = panel.copy()
    by_date = p.groupby('trade_date')

    for src, dst in (('ret_5d', 'cs_ret_5d'), ('ret_20d', 'cs_ret_20d'),
                     ('foreign_5d', 'cs_foreign_5d'), ('total_5d', 'cs_total_5d'),
                     ('vol_ratio', 'cs_vol_ratio'), ('rsi_14', 'cs_rsi'),
                     ('vol_20d', 'cs_vol_20d')):
        p[dst] = by_date[src].rank(pct=True)

    p['mkt_ret_1d'] = by_date['ret_1d'].transform('mean')
    p['mkt_ret_5d'] = by_date['ret_5d'].transform('mean')
    p['mkt_breadth'] = by_date['ret_1d'].transform(lambda s: (s > 0).mean())
    p['mkt_vol_20d'] = by_date['vol_20d'].transform('mean')
    p['mkt_chip_breadth'] = by_date['total_1d'].transform(lambda s: (s > 0).mean())
    return p


def build_panel(raw: pd.DataFrame) -> pd.DataFrame:
    """原始多股票資料 → 完整特徵面板（訓練與推論共用入口）。"""
    frames = []
    for sid, g in raw.groupby('stock_id'):
        if len(g) < MIN_HISTORY:
            continue
        f = build_stock_features(g)
        f['stock_id'] = sid
        frames.append(f)
    if not frames:
        return pd.DataFrame()
    panel = pd.concat(frames, ignore_index=True).sort_values(['trade_date', 'stock_id'])
    return add_cross_sectional(panel).reset_index(drop=True)


LOAD_SQL = """
    SELECT p.stock_id, p.trade_date,
           p.open_price  AS open,  p.high_price AS high,
           p.low_price   AS low,   p.close_price AS close,
           -- 計算報酬率一律用 adj_close（已還原除權息與減資）；
           -- close 僅供顯示。缺值時退回 close，避免舊資料造成 NULL。
           COALESCE(p.adj_close, p.close_price) AS adj_close,
           p.volume, p.turnover_value AS turnover, p.transaction_count AS trades,
           c.foreign_investor_buy  AS foreign_net,
           c.investment_trust_buy  AS trust_net,
           c.dealer_buy            AS dealer_net,
           c.total_net_buy         AS total_net,
           c.foreign_holding_ratio AS holding_ratio
    FROM stock_daily_prices p
    LEFT JOIN stock_chip_analysis c USING (stock_id, trade_date)
    WHERE p.close_price > 0
    ORDER BY p.stock_id, p.trade_date
"""
