"""
M3 籌碼模型共用特徵工程

訓練（RandomForest/train_m3.py）與推論（model3_chip.py）共用，
確保特徵定義一致。所有特徵僅使用當日（含）以前的資料，無未來洩漏。

輸入 DataFrame 需含欄位（單一股票、依 trade_date 遞增排序）：
  trade_date, foreign_net, trust_net, dealer_net, total_net, volume, close

兩層特徵：
  FEATURE_COLS     個股時序特徵（build_features，單股即可算）
  CS_FEATURE_COLS  橫斷面特徵（build_cross_sectional，需同日全體追蹤股票）
                   —— Iteration 9 新增：「外資買超 0.5 倍均量」在全體皆被買超時
                   與只有這檔被買超時意義完全不同，需要同儕情境才判斷得出來。
"""

import numpy as np
import pandas as pd

# 特徵欄位（順序即模型輸入順序）
FEATURE_COLS = [
    'foreign_1d', 'trust_1d', 'dealer_1d', 'total_1d',      # 當日買賣超 / 20日均量
    'foreign_3d', 'trust_3d', 'total_3d',                   # 3 日累計 / 20日均量
    'foreign_5d', 'trust_5d', 'total_5d',                   # 5 日累計 / 20日均量
    'buy_days_5',                                           # 近 5 日買超天數（0~5）
    'foreign_buy_days_5',                                   # 近 5 日外資買超天數
    'align_foreign_trust',                                  # 外資投信同向（+1/0/-1）
    'ret_5d', 'ret_20d',                                    # 價格動能
    'vol_ratio',                                            # 當日量 / 20日均量
]

# 橫斷面特徵（當日全體追蹤股票之間的相對位置）
CS_FEATURE_COLS = [
    'cs_foreign_5d', 'cs_total_5d', 'cs_trust_5d',   # 法人買超的同儕百分位
    'cs_ret_5d', 'cs_ret_20d', 'cs_vol_ratio',       # 動能與量能的同儕百分位
    'mkt_breadth',                                   # 當日買超家數比例（大盤籌碼氛圍）
    'mkt_ret_5d',                                    # 當日全體 ret_5d 平均（大盤動能）
]

# 模型實際輸入 = 個股時序 + 橫斷面
MODEL_FEATURE_COLS = FEATURE_COLS + CS_FEATURE_COLS

# 橫斷面排名來源欄位 → 目標欄位
_CS_RANK_SRC = [
    ('foreign_5d', 'cs_foreign_5d'), ('total_5d', 'cs_total_5d'),
    ('trust_5d', 'cs_trust_5d'), ('ret_5d', 'cs_ret_5d'),
    ('ret_20d', 'cs_ret_20d'), ('vol_ratio', 'cs_vol_ratio'),
]

MIN_HISTORY = 25   # 至少需要的歷史天數（20日均量 + 5日窗口）


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """回傳含 FEATURE_COLS 的 DataFrame（歷史不足的前段列已 dropna）。"""
    df = df.sort_values('trade_date').reset_index(drop=True).copy()

    for col in ['foreign_net', 'trust_net', 'dealer_net', 'total_net']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
    df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
    df['close']  = pd.to_numeric(df['close'], errors='coerce')

    # 20 日均量作為標準化基準（股數）
    vol20 = df['volume'].rolling(20, min_periods=10).mean()

    df['foreign_1d'] = df['foreign_net'] / vol20
    df['trust_1d']   = df['trust_net'] / vol20
    df['dealer_1d']  = df['dealer_net'] / vol20
    df['total_1d']   = df['total_net'] / vol20

    for n in (3, 5):
        df[f'foreign_{n}d'] = df['foreign_net'].rolling(n).sum() / vol20
        df[f'trust_{n}d']   = df['trust_net'].rolling(n).sum() / vol20
        df[f'total_{n}d']   = df['total_net'].rolling(n).sum() / vol20

    df['buy_days_5'] = (df['total_net'] > 0).rolling(5).sum()
    df['foreign_buy_days_5'] = (df['foreign_net'] > 0).rolling(5).sum()

    f5 = df['foreign_net'].rolling(5).sum()
    t5 = df['trust_net'].rolling(5).sum()
    df['align_foreign_trust'] = np.sign(f5) * np.sign(t5)

    df['ret_5d']  = df['close'].pct_change(5)
    df['ret_20d'] = df['close'].pct_change(20)
    df['vol_ratio'] = df['volume'] / vol20

    return df.dropna(subset=FEATURE_COLS)


def build_cross_sectional(panel: pd.DataFrame) -> pd.DataFrame:
    """
    在多股票面板上加計橫斷面特徵。

    輸入：build_features 產出的多股票 DataFrame（需含 trade_date 與 FEATURE_COLS）。
    輸出：同一 DataFrame 加上 CS_FEATURE_COLS。

    僅使用「當日同儕」資訊，不跨日、不看未來，因此無洩漏。
    """
    panel = panel.copy()
    by_date = panel.groupby('trade_date')
    for src, dst in _CS_RANK_SRC:
        panel[dst] = by_date[src].rank(pct=True)
    panel['mkt_breadth'] = by_date['total_1d'].transform(lambda s: (s > 0).mean())
    panel['mkt_ret_5d']  = by_date['ret_5d'].transform('mean')
    return panel


def build_panel(raw: pd.DataFrame) -> pd.DataFrame:
    """多股票原始資料 → 個股時序特徵 → 橫斷面特徵（訓練與推論共用入口）。"""
    frames = []
    for sid, g in raw.groupby('stock_id'):
        feat = build_features(g)
        if feat.empty:
            continue
        feat['stock_id'] = sid
        frames.append(feat)
    if not frames:
        return pd.DataFrame(columns=['stock_id', 'trade_date'] + MODEL_FEATURE_COLS)
    panel = pd.concat(frames, ignore_index=True).sort_values(['trade_date', 'stock_id'])
    return build_cross_sectional(panel).reset_index(drop=True)
