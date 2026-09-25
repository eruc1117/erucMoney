"""
從 PostgreSQL 載入股票資料，並轉換為 LSTM 可用的序列格式
"""
import logging

import numpy as np
import pandas as pd
import psycopg2
from sklearn.preprocessing import MinMaxScaler

from config import DB, LOOKBACK, FORECAST_STEPS, TRAIN_RATIO, VAL_RATIO

logger = logging.getLogger(__name__)


# ── 資料庫連線 ─────────────────────────────────────────────────────────────────
from contextlib import contextmanager


@contextmanager
def get_conn():
    """
    每次呼叫開一條新連線，用完**確實關閉**。

    psycopg2 的 `with connection` 只會 commit／rollback，**不會關閉連線**——
    原本寫成 `with get_conn() as conn:` 等於每次查詢洩漏一條連線。
    預測伺服器一次可能並行跑十個模型，累積下來會撞上 PostgreSQL 的連線上限，
    而症狀會是難以理解的資料庫錯誤，不是「連線太多」。
    """
    conn = psycopg2.connect(
        host=DB["host"], port=DB["port"], dbname=DB["dbname"],
        user=DB["user"], password=DB["password"],
    )
    try:
        yield conn
    finally:
        conn.close()


def get_all_stocks() -> list[str]:
    """回傳 stock_daily_prices 中有資料的所有股票代碼（按代碼排序）"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT stock_id
                FROM stock_daily_prices
                ORDER BY stock_id
            """)
            return [row[0] for row in cur.fetchall()]


def load_prices(stock_id: str) -> pd.DataFrame:
    """
    載入個股每日行情，按 trade_date 遞增排序。

    會濾掉收盤價 <= 0 的無效列（Iteration 11 新增）。
    實測 2449（2024-04-26）與 3037（2022-02-22）各有一列 OHLC 與成交量全為 0，
    顯然是爬蟲寫入的佔位資料。這種列的殺傷力遠超過「少一天」：
      · 報酬率 = diff/前收 會除以 0，實測整體日報酬標準差被推到 1.8 億
      · 含 0 的視窗其 z-score 標準差暴增，正規化後的輸入完全失真
    因此在載入層一律排除，避免任何模型被單一壞列汙染。
    """
    sql = """
        SELECT trade_date, open_price, high_price, low_price,
               close_price, volume, change_value, change_rate
        FROM stock_daily_prices
        WHERE stock_id = %s
        ORDER BY trade_date ASC
    """
    with get_conn() as conn:
        df = pd.read_sql(sql, conn, params=(stock_id,), parse_dates=["trade_date"])
    df = df.set_index("trade_date")
    df = df.apply(pd.to_numeric, errors="coerce")
    df = df.dropna(subset=["close_price"])

    invalid = df["close_price"] <= 0
    if invalid.any():
        logger.warning("[data_loader] %s 濾除 %d 列無效收盤價（<= 0）：%s",
                       stock_id, int(invalid.sum()),
                       [str(d)[:10] for d in df.index[invalid][:5]])
        df = df[~invalid]
    return df


def load_us_prices(ticker: str) -> pd.DataFrame:
    """
    載入美股日行情（`us_daily_prices`），欄位語意與 `load_prices` 對齊。

    跨股票 LSTM 的輸入是 z-score 後的收盤價視窗，與價格尺度無關，
    所以同一批模型可以直接套在美股上——這不代表它在美股上有 edge：
    Iteration 32 實測只用美股自身歷史，什麼都預測不出來（相關 0.0085），
    與台股的 Iteration 11 結論一致。前端的「無 edge」標記照樣要掛著。
    """
    sql = """
        SELECT trade_date, open_price, high_price, low_price,
               close_price, volume
        FROM us_daily_prices
        WHERE ticker = %s
        ORDER BY trade_date ASC
    """
    with get_conn() as conn:
        df = pd.read_sql(sql, conn, params=(ticker,), parse_dates=["trade_date"])
    df = df.set_index("trade_date")
    df = df.apply(pd.to_numeric, errors="coerce")
    df = df.dropna(subset=["close_price"])
    df = df[df["close_price"] > 0]
    return df


def load_chips(stock_id: str) -> pd.DataFrame:
    """載入三大法人籌碼資料"""
    sql = """
        SELECT trade_date,
               foreign_investor_buy, investment_trust_buy,
               dealer_buy, total_net_buy, foreign_holding_ratio
        FROM stock_chip_analysis
        WHERE stock_id = %s
        ORDER BY trade_date ASC
    """
    with get_conn() as conn:
        df = pd.read_sql(sql, conn, params=(stock_id,), parse_dates=["trade_date"])
    if df.empty:
        return df
    df = df.set_index("trade_date")
    df = df.apply(pd.to_numeric, errors="coerce")
    return df


def load_full(stock_id: str) -> pd.DataFrame:
    """合併行情 + 籌碼資料（左合併，缺失籌碼補 0）"""
    prices = load_prices(stock_id)
    chips  = load_chips(stock_id)
    if chips.empty:
        return prices
    df = prices.join(chips, how="left")
    chip_cols = ["foreign_investor_buy", "investment_trust_buy",
                 "dealer_buy", "total_net_buy", "foreign_holding_ratio"]
    for col in chip_cols:
        if col in df.columns:
            df[col] = df[col].fillna(0)
    return df


# ── 序列建立 ───────────────────────────────────────────────────────────────────
def make_sequences(data: np.ndarray, lookback: int = LOOKBACK,
                   forecast: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """
    data   : 2D array (timesteps, features)
    lookback: 輸入窗口長度
    forecast: 預測步數（1 = 單步，>1 = 多步 Seq2Seq）

    Returns X: (samples, lookback, features), y: (samples, forecast)
    """
    X, y = [], []
    target_idx = 0  # close_price 永遠為第 0 欄
    for i in range(len(data) - lookback - forecast + 1):
        X.append(data[i : i + lookback])
        y.append(data[i + lookback : i + lookback + forecast, target_idx])
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)


def split_sequences(X: np.ndarray, y: np.ndarray,
                    train_ratio: float = TRAIN_RATIO,
                    val_ratio:   float = VAL_RATIO):
    """依時間順序切割 train / val / test，不做 shuffle"""
    n = len(X)
    n_train = int(n * train_ratio)
    n_val   = int(n * val_ratio)

    X_train = X[:n_train]
    y_train = y[:n_train]
    X_val   = X[n_train : n_train + n_val]
    y_val   = y[n_train : n_train + n_val]
    X_test  = X[n_train + n_val:]
    y_test  = y[n_train + n_val:]
    return X_train, y_train, X_val, y_val, X_test, y_test


def prepare_single_feature(stock_id: str, lookback: int = LOOKBACK):
    """
    M01–M03 用：只使用 close_price 單特徵
    Returns: (splits_tuple, scaler, raw_close_test)
    """
    df = load_prices(stock_id)
    if len(df) < lookback + 10:
        return None

    close = df["close_price"].values.reshape(-1, 1)
    scaler = MinMaxScaler()
    scaled = scaler.fit_transform(close)

    X, y = make_sequences(scaled, lookback=lookback, forecast=1)
    y = y.reshape(-1, 1)
    splits = split_sequences(X, y)
    return splits, scaler


def prepare_multi_feature(stock_id: str, feature_cols: list[str],
                           lookback: int = LOOKBACK, forecast: int = 1,
                           use_chips: bool = False):
    """
    多特徵版本，feature_cols[0] 必須是 close_price（預測目標）
    Returns: (splits_tuple, scalers_dict)
    """
    df = load_full(stock_id) if use_chips else load_prices(stock_id)
    cols_present = [c for c in feature_cols if c in df.columns]
    if not cols_present or len(df) < lookback + 10:
        return None

    df_feat = df[cols_present].copy().ffill().fillna(0)

    scalers = {}
    scaled_parts = []
    for col in cols_present:
        sc = MinMaxScaler()
        scaled_parts.append(sc.fit_transform(df_feat[[col]]))
        scalers[col] = sc

    scaled = np.hstack(scaled_parts)  # (T, F)
    X, y = make_sequences(scaled, lookback=lookback, forecast=forecast)
    if forecast == 1:
        y = y.reshape(-1, 1)
    splits = split_sequences(X, y)
    return splits, scalers


# ── IMP-001：單特徵 Log Return 預測目標 ────────────────────────────────────────

def prepare_single_logreturn(stock_id: str, lookback: int = LOOKBACK):
    """
    IMP-001：預測目標改為對數報酬率。
    使用 MinMax 正規化 log_return 序列（近平穩，可直接 MinMax）。

    Returns
    -------
    splits        : (X_tr, y_tr, X_val, y_val, X_te, y_te)
                    X 為正規化 log_return，y 為下一期正規化 log_return
    scaler        : MinMaxScaler（log_return 的 scaler，供 inverse_transform）
    last_close_te : 測試集每個樣本的「前一日收盤價」（用於換算回絕對價格）
    """
    df = load_prices(stock_id)
    if df is None or len(df) < lookback + 10:
        return None

    close = df["close_price"].values                        # 全部收盤價
    log_ret = np.log(close[1:] / close[:-1])               # 長度 T-1
    close_prev = close[:-1]                                  # 對應的前一日收盤

    scaler = MinMaxScaler()
    scaled = scaler.fit_transform(log_ret.reshape(-1, 1))   # (T-1, 1)

    X, y = make_sequences(scaled, lookback=lookback, forecast=1)
    y = y.reshape(-1, 1)

    n = len(X)
    # 每筆樣本的 last close = close_prev[i + lookback]（即視窗最後一日的收盤）
    last_close = close_prev[np.arange(n) + lookback].astype(np.float32)

    splits = split_sequences(X, y)
    n_train = int(n * TRAIN_RATIO)
    n_val   = int(n * VAL_RATIO)
    last_close_te = last_close[n_train + n_val:]

    return splits, scaler, last_close_te


# ── IMP-003：多特徵滾動 Z-score 正規化 ─────────────────────────────────────────

def make_zscore_sequences_multi(data: np.ndarray, lookback: int = LOOKBACK,
                                 target_col: int = 0, eps: float = 1e-8):
    """
    IMP-003：多特徵版本的滾動（視窗級）Z-score 正規化。
    每個訓練樣本只使用其輸入視窗內的統計量做標準化，
    避免全域 MinMax 造成的未來資料洩漏（Data Leakage）。

    Parameters
    ----------
    data       : (T, F) 原始特徵陣列（F 個特徵，T 個時間步）
    lookback   : 輸入視窗長度
    target_col : 預測目標欄位的索引（預設 0，即 log_return）
    eps        : 避免除以 0

    Returns
    -------
    X           : (N, lookback, F)  正規化輸入序列
    y           : (N, 1)            正規化目標值（下一期 target_col）
    norm_params : (N, F, 2)         每樣本每特徵的 [mean, std]（供反正規化）
    """
    T, F = data.shape
    X, y, norm_params = [], [], []

    for i in range(T - lookback):
        window = data[i: i + lookback]          # (lookback, F)
        means  = window.mean(axis=0)            # (F,)
        stds   = window.std(axis=0) + eps       # (F,)

        x_norm = (window - means) / stds        # (lookback, F)

        # 目標：視窗後第一個時間步的 target_col，以同欄的 mean/std 正規化
        next_val = data[i + lookback, target_col]
        y_norm   = (next_val - means[target_col]) / stds[target_col]

        X.append(x_norm)
        y.append([y_norm])
        norm_params.append(np.stack([means, stds], axis=-1))  # (F, 2)

    return (np.array(X, dtype=np.float32),
            np.array(y, dtype=np.float32),
            np.array(norm_params, dtype=np.float32))


# ── IMP-001+002+003：Log Return + 多特徵 + Rolling Z-score ─────────────────────

def prepare_logreturn_enhanced(stock_id: str, lookback: int = LOOKBACK,
                                use_zscore: bool = True):
    """
    IMP-001+002+003 組合版資料管線：
    - 預測目標：log_return（IMP-001，去趨勢）
    - 10 個輸入特徵（IMP-002）
    - 正規化：rolling z-score（IMP-003，use_zscore=True）
              或 MinMax（use_zscore=False，做為對照）

    Parameters
    ----------
    stock_id   : 股票代碼
    lookback   : 輸入視窗長度
    use_zscore : True → Rolling Z-score（IMP-003）；False → MinMax（基準）

    Returns（use_zscore=True）
    -------------------------
    splits         : (X_tr, y_tr, X_val, y_val, X_te, y_te)
    norm_params_te : (N_test, F, 2) — 測試集每樣本每特徵的 [mean, std]
    last_close_te  : (N_test,)      — 測試集每樣本視窗末日收盤價
    cols           : list[str]      — 實際使用的特徵名稱（log_return 在索引 0）

    Returns（use_zscore=False）
    --------------------------
    splits         : 同上
    scalers        : dict[col -> MinMaxScaler]
    last_close_te  : 同上
    cols           : 同上
    """
    from features import build_enhanced_features, M01_ENHANCED_COLS

    df = load_prices(stock_id)
    if df is None or len(df) < lookback + 40:   # 40 = 技術指標熱身期
        return None

    df = build_enhanced_features(df)             # 加入所有技術指標 + log_return，dropna

    cols = [c for c in M01_ENHANCED_COLS if c in df.columns]
    if len(cols) < 5 or "log_return" not in cols:
        return None

    # log_return 必須在第 0 欄（target_col=0）
    if cols[0] != "log_return":
        cols = ["log_return"] + [c for c in cols if c != "log_return"]

    close_vals = df["close_price"].values          # 用於計算 last_close
    data = df[cols].values.astype(np.float32)      # (T, F)
    n_raw = len(data)

    if use_zscore:
        # ── Rolling Z-score（IMP-003）─────────────────────────────────────────
        X, y, norm_params = make_zscore_sequences_multi(
            data, lookback=lookback, target_col=0)

        n = len(X)
        # 每樣本的 last_close：data 第 i+lookback-1 行對應 df.iloc[i+lookback-1]
        # 收盤價欄位是 close_vals（已對齊 df，dropna 後）
        last_close = close_vals[np.arange(n) + lookback - 1].astype(np.float32)

        splits    = split_sequences(X, y)
        n_train   = int(n * TRAIN_RATIO)
        n_val     = int(n * VAL_RATIO)
        norm_te   = norm_params[n_train + n_val:]
        lc_te     = last_close[n_train + n_val:]
        return splits, norm_te, lc_te, cols

    else:
        # ── MinMax 對照組 ────────────────────────────────────────────────────
        scalers, parts = {}, []
        for col in cols:
            sc = MinMaxScaler()
            col_idx = cols.index(col)
            parts.append(sc.fit_transform(data[:, [col_idx]]))
            scalers[col] = sc
        scaled = np.hstack(parts)                  # (T, F)

        X, y = make_sequences(scaled, lookback=lookback, forecast=1)
        y    = y.reshape(-1, 1)

        n = len(X)
        last_close = close_vals[np.arange(n) + lookback - 1].astype(np.float32)

        splits  = split_sequences(X, y)
        n_train = int(n * TRAIN_RATIO)
        n_val   = int(n * VAL_RATIO)
        lc_te   = last_close[n_train + n_val:]
        return splits, scalers, lc_te, cols


# ── 跨股票正規化（Window-level Z-score）────────────────────────────────────────
def make_zscore_sequences(close: np.ndarray, lookback: int = LOOKBACK,
                          eps: float = 1e-8):
    """
    以每個窗口自身的 mean/std 做 z-score 正規化，使模型尺度無關，
    可跨股票（不同價位）直接套用。

    close : 1D array，收盤價時間序列（原始價格）
    Returns
    -------
    X          : (N, lookback, 1)  正規化輸入序列
    y          : (N, 1)            正規化目標（下一日收盤）
    norm_params: (N, 2)            每筆樣本的 [mean, std]（用於反正規化）
    """
    X, y, norm_params = [], [], []
    for i in range(len(close) - lookback):
        window = close[i : i + lookback]
        mean   = window.mean()
        std    = window.std() + eps

        x_norm = (window - mean) / std          # (lookback,)
        y_norm = (close[i + lookback] - mean) / std  # scalar

        X.append(x_norm.reshape(-1, 1))
        y.append([y_norm])
        norm_params.append([mean, std])

    return (np.array(X, dtype=np.float32),
            np.array(y, dtype=np.float32),
            np.array(norm_params, dtype=np.float32))


def make_zscore_sequences_seq2seq(close: np.ndarray, lookback: int = LOOKBACK,
                                  forecast_steps: int = 5, eps: float = 1e-8):
    """
    Seq2Seq 用的多步序列（Iteration 11 新增）。

    與 `make_zscore_sequences` 相同的視窗級 z-score，但目標是未來
    `forecast_steps` 天，形狀 (N, forecast_steps, 1)——這正是 M07 需要、
    而舊管線無法提供的格式（舊 `train_cross.py` 因此把 m07 列入跳過清單）。

    Returns
    -------
    X          : (N, lookback, 1)
    y          : (N, forecast_steps, 1)
    norm_params: (N, 2)  每筆樣本的 [mean, std]
    """
    X, y, norm_params = [], [], []
    for i in range(len(close) - lookback - forecast_steps + 1):
        window = close[i: i + lookback]
        mean = window.mean()
        std = window.std() + eps

        future = close[i + lookback: i + lookback + forecast_steps]
        X.append(((window - mean) / std).reshape(-1, 1))
        y.append(((future - mean) / std).reshape(-1, 1))
        norm_params.append([mean, std])

    return (np.array(X, dtype=np.float32),
            np.array(y, dtype=np.float32),
            np.array(norm_params, dtype=np.float32))


def prepare_cross_stock_seq2seq(stock_ids: list[str] | None = None,
                                lookback: int = LOOKBACK,
                                forecast_steps: int = 5,
                                train_ratio: float = TRAIN_RATIO,
                                val_ratio: float = VAL_RATIO):
    """跨股票多步資料集，切分方式與 `prepare_cross_stock_data` 一致。"""
    if stock_ids is None:
        stock_ids = get_all_stocks()

    parts = {s: {"X": [], "y": [], "np": []} for s in ("train", "val", "test")}
    stock_labels_test = []

    for sid in stock_ids:
        df = load_prices(sid)
        if df is None or len(df) < lookback + forecast_steps + 10:
            continue

        close = df["close_price"].values
        X, y, np_arr = make_zscore_sequences_seq2seq(
            close, lookback=lookback, forecast_steps=forecast_steps)

        n = len(X)
        n_train = int(n * train_ratio)
        n_val = int(n * val_ratio)

        parts["train"]["X"].append(X[:n_train])
        parts["train"]["y"].append(y[:n_train])
        parts["val"]["X"].append(X[n_train: n_train + n_val])
        parts["val"]["y"].append(y[n_train: n_train + n_val])
        parts["test"]["X"].append(X[n_train + n_val:])
        parts["test"]["y"].append(y[n_train + n_val:])
        parts["test"]["np"].append(np_arr[n_train + n_val:])
        stock_labels_test.extend([sid] * len(X[n_train + n_val:]))

    def concat(lst):
        return np.concatenate(lst, axis=0) if lst else np.array([])

    splits = (concat(parts["train"]["X"]), concat(parts["train"]["y"]),
              concat(parts["val"]["X"]),   concat(parts["val"]["y"]),
              concat(parts["test"]["X"]),  concat(parts["test"]["y"]))
    return splits, concat(parts["test"]["np"]), stock_labels_test


def prepare_cross_stock_data(stock_ids: list[str] | None = None,
                              lookback: int = LOOKBACK,
                              train_ratio: float = TRAIN_RATIO,
                              val_ratio:   float = VAL_RATIO):
    """
    載入多支股票，合併為跨股票訓練集（Z-score 正規化）。

    每支股票依時間順序切 train/val/test 後再合併，
    避免資訊洩漏（test 資料永遠是各股票最新的 15%）。

    Returns
    -------
    splits      : (X_tr, y_tr, X_val, y_val, X_te, y_te)
    norm_params_test : (N_test, 2)  測試集的 [mean, std]，用於反正規化
    stock_ids_test   : 測試集各樣本對應的股票代碼
    """
    if stock_ids is None:
        stock_ids = get_all_stocks()

    parts = {s: {"X": [], "y": [], "np": []} for s in ("train", "val", "test")}
    stock_labels_test = []

    for sid in stock_ids:
        df = load_prices(sid)
        if df is None or len(df) < lookback + 10:
            continue

        close = df["close_price"].values
        X, y, np_arr = make_zscore_sequences(close, lookback=lookback)

        n       = len(X)
        n_train = int(n * train_ratio)
        n_val   = int(n * val_ratio)

        parts["train"]["X"].append(X[:n_train])
        parts["train"]["y"].append(y[:n_train])
        parts["val"]["X"].append(X[n_train : n_train + n_val])
        parts["val"]["y"].append(y[n_train : n_train + n_val])
        parts["test"]["X"].append(X[n_train + n_val:])
        parts["test"]["y"].append(y[n_train + n_val:])
        parts["test"]["np"].append(np_arr[n_train + n_val:])
        stock_labels_test.extend([sid] * len(X[n_train + n_val:]))

    def concat(lst):
        return np.concatenate(lst, axis=0) if lst else np.array([])

    X_tr  = concat(parts["train"]["X"])
    y_tr  = concat(parts["train"]["y"])
    X_val = concat(parts["val"]["X"])
    y_val = concat(parts["val"]["y"])
    X_te  = concat(parts["test"]["X"])
    y_te  = concat(parts["test"]["y"])
    np_te = concat(parts["test"]["np"])

    return (X_tr, y_tr, X_val, y_val, X_te, y_te), np_te, stock_labels_test
