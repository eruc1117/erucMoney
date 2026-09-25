"""
外生特徵實驗：美股隔夜與台指期夜盤能不能讓 LSTM 有用（Iteration 28）
──────────────────────────────────────────────────────────────
Iteration 11 的結論是：10 種 LSTM 的 MAE 全部落在 5.17~5.25，而天真基準
（明日＝今日）是 5.20；方向準確率 46.9~50.6%。當時寫下的建議是
**「要讓 LSTM 有用得換輸入（籌碼／新聞）而非換架構」**——這支實驗就是照做。

## 為什麼這次可能不一樣

台指期夜盤（15:00~翌日 05:00）在台股開盤前就定好了次日開盤價，
Iteration 28 實測它對個股跳空的相關達 0.567（費半只有 0.483）。

而明日收盤 = 今日收盤 ×（1＋跳空）×（1＋盤中報酬）。跳空這一段是**可預測的**，
盤中那一段不是。所以理論上，知道夜盤應該能實質改善「收盤到收盤」的預測——
改善的不是預測能力，而是把一段原本被當成隨機的變異挪進了可解釋的部分。

**這不是資訊洩漏**：夜盤在台股開盤前就結束，做預測時真的拿得到。

## 評估一律用天真基準對照

Iteration 11 建立的規矩：`evaluate.compute_metrics` 的方向準確率會跨越股票
邊界、數值不可信。這裡自行計算，逐檔切開，並與「明日＝今日」逐項對照。
沒有勝過基準的模型，準確率再好看都不算數。

用法（需 LSTM venv）：
    cd LSTM && venv\\Scripts\\python.exe experiment_exog.py
產出：results/exog_experiment.md
"""

import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

# LSTM 與 Crawler 各有一個 config.py，順序放反會 import 到錯的那個
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from config import DB, RESULTS_DIR                                   # noqa: E402

LOOKBACK = 20
EPOCHS = 40
BATCH = 64
PATIENCE = 6
SEED = 42

PRICE_SQL = """
    SELECT stock_id, trade_date, open_price, high_price, low_price,
           close_price, COALESCE(adj_close, close_price) AS adj_close, volume
      FROM stock_daily_prices
     WHERE close_price > 0 AND open_price > 0
     ORDER BY stock_id, trade_date
"""
US_SQL = """
    SELECT ticker, trade_date, close_price FROM us_daily_prices
     WHERE close_price > 0 ORDER BY trade_date
"""
NIGHT_SQL = """
    SELECT trade_date, session, open_price, high_price, low_price,
           close_price, volume
      FROM futures_daily WHERE futures_id = 'TX' AND close_price > 0
     ORDER BY trade_date, session
"""


def conn():
    import psycopg2
    return psycopg2.connect(host=DB['host'], port=DB['port'], dbname=DB['dbname'],
                            user=DB['user'], password=DB['password'])


def load_panel() -> pd.DataFrame:
    """個股價量 + 美股隔夜 + 夜盤，全部對齊到台股交易日。"""
    with conn() as c:
        px = pd.read_sql(PRICE_SQL, c)
        us = pd.read_sql(US_SQL, c)
        night = pd.read_sql(NIGHT_SQL, c)

    px['trade_date'] = pd.to_datetime(px['trade_date'])
    px = px.sort_values(['stock_id', 'trade_date'])
    g = px.groupby('stock_id')
    px['ret'] = g['adj_close'].transform(lambda s: s.pct_change())
    px['vol20'] = px.groupby('stock_id')['ret'].transform(lambda s: s.rolling(20).std())
    px['ret5'] = g['adj_close'].transform(lambda s: s.pct_change(5))

    # ── 美股：台股 D 日反映的是「D 之前最後一個美股交易日」──────────────
    us['trade_date'] = pd.to_datetime(us['trade_date'])
    piv = us.pivot(index='trade_date', columns='ticker', values='close_price').sort_index()
    usr = (piv / piv.shift(1) - 1).reset_index().rename(columns={'trade_date': 'us_date'})
    keep = [c for c in ('SOXX', 'QQQ', 'NVDA', 'TSM') if c in usr.columns]
    usr = usr[['us_date'] + keep].rename(columns={c: f'us_{c}' for c in keep})
    dates = pd.DataFrame({'trade_date': sorted(px['trade_date'].unique())})
    aligned_us = pd.merge_asof(dates.sort_values('trade_date'),
                               usr.sort_values('us_date'),
                               left_on='trade_date', right_on='us_date',
                               allow_exact_matches=False).drop(columns=['us_date'])

    # ── 夜盤：after_market 那列領先**同日**開盤，故直接以 trade_date 對齊 ──
    night['trade_date'] = pd.to_datetime(night['trade_date'])
    np_ = night.pivot(index='trade_date', columns='session').sort_index()

    def nc(field, ses):
        try:
            return np_[(field, ses)].astype(float)
        except KeyError:
            return pd.Series(np.nan, index=np_.index)

    prev_day_close = nc('close_price', 'position').shift(1)
    n_close, n_open = nc('close_price', 'after_market'), nc('open_price', 'after_market')
    n_high, n_low = nc('high_price', 'after_market'), nc('low_price', 'after_market')
    nf = pd.DataFrame({
        'night_ret': n_close / prev_day_close - 1,
        'night_range': (n_high - n_low) / prev_day_close,
        'night_drift': n_close / n_open.replace(0, np.nan) - 1,
    }, index=np_.index)
    nf = nf.replace([np.inf, -np.inf], np.nan)
    nf.loc[nf['night_ret'].abs() > 0.15, 'night_ret'] = np.nan
    nf = nf.reset_index()

    out = px.merge(aligned_us, on='trade_date', how='left').merge(nf, on='trade_date', how='left')
    return out


FEATURE_SETS = {
    '純價格（現行）': ['ret', 'ret5', 'vol20'],
    '+ 美股隔夜': ['ret', 'ret5', 'vol20', 'us_SOXX', 'us_QQQ'],
    '+ 台指期夜盤': ['ret', 'ret5', 'vol20', 'night_ret', 'night_range', 'night_drift'],
    '+ 美股 + 夜盤': ['ret', 'ret5', 'vol20', 'us_SOXX', 'us_QQQ',
                    'night_ret', 'night_range', 'night_drift'],
}


def build_sequences(d: pd.DataFrame, cols: list, require: list = None):
    """
    目標＝明日的**報酬率**而非價格。

    直接預測價格會讓模型只要複製今天的收盤就有很低的 MAE，
    看起來很準卻毫無資訊（Iteration 11 的 10 個模型就是這樣）。
    預測報酬率把那個捷徑堵死，模型必須真的說出「會往哪走」。
    """
    Xs, ys, metas = [], [], []
    for sid, g in d.groupby('stock_id'):
        g = g.sort_values('trade_date').reset_index(drop=True)
        # require：所有變體共同需要的欄位。不強制對齊的話，夜盤 2018 才有、
        # 股價回溯到 1992，各變體會跑在完全不同的樣本上——
        # 那比的是資料量而不是特徵（天真基準 MAE 會跟著變，一眼就能看出）。
        g = g.dropna(subset=list(dict.fromkeys((require or cols) + cols + ['ret'])))
        if len(g) < LOOKBACK + 30:
            continue
        arr = g[cols].values.astype('float32')
        tgt = g['ret'].shift(-1).values.astype('float32')   # 明日報酬
        close = g['adj_close'].values.astype('float32')
        for i in range(LOOKBACK, len(g) - 1):
            Xs.append(arr[i - LOOKBACK:i])
            ys.append(tgt[i])
            metas.append((sid, g['trade_date'].iloc[i], close[i], close[i + 1]))
    return np.array(Xs), np.array(ys), pd.DataFrame(
        metas, columns=['stock_id', 'trade_date', 'close', 'next_close'])


def run_variant(label: str, cols: list, panel: pd.DataFrame, require: list = None) -> dict:
    import tensorflow as tf
    from tensorflow.keras import layers, models
    tf.random.set_seed(SEED)
    np.random.seed(SEED)

    X, y, meta = build_sequences(panel, cols, require)
    if len(X) < 5000:
        return {'label': label, 'skip': f'樣本不足（{len(X)}）'}

    # 時序切分：訓練集必須全部早於測試集，否則等於偷看未來
    order = np.argsort(meta['trade_date'].values)
    X, y, meta = X[order], y[order], meta.iloc[order].reset_index(drop=True)
    n_tr, n_va = int(len(X) * 0.70), int(len(X) * 0.85)

    mu = X[:n_tr].reshape(-1, X.shape[2]).mean(axis=0)
    sd = X[:n_tr].reshape(-1, X.shape[2]).std(axis=0) + 1e-8
    Xn = (X - mu) / sd

    m = models.Sequential([
        layers.Input(shape=(LOOKBACK, X.shape[2])),
        layers.LSTM(48, return_sequences=True),
        layers.Dropout(0.2),
        layers.LSTM(24),
        layers.Dropout(0.2),
        layers.Dense(1),
    ])
    m.compile(optimizer=tf.keras.optimizers.Adam(1e-3), loss='mse')
    m.fit(Xn[:n_tr], y[:n_tr], validation_data=(Xn[n_tr:n_va], y[n_tr:n_va]),
          epochs=EPOCHS, batch_size=BATCH, verbose=0,
          callbacks=[tf.keras.callbacks.EarlyStopping(patience=PATIENCE,
                                                      restore_best_weights=True)])

    pred = m.predict(Xn[n_va:], verbose=0).ravel()
    true = y[n_va:]
    mt = meta.iloc[n_va:].reset_index(drop=True)

    # ── 天真基準：明日報酬 = 0（等同「明日＝今日」）────────────────────
    naive = np.zeros_like(true)
    mae, mae_naive = np.mean(np.abs(pred - true)), np.mean(np.abs(naive - true))
    up = true > 0
    # 方向基準用多數類別，不是「猜零」——猜零沒有方向可言
    base_dir = max(up.mean(), 1 - up.mean())
    dir_acc = float(np.mean(np.sign(pred) == np.sign(true)))
    corr = float(np.corrcoef(pred, true)[0, 1]) if pred.std() > 0 else 0.0

    return {
        'label': label, 'n_features': len(cols), 'n_test': int(len(true)),
        'mae': float(mae), 'mae_naive': float(mae_naive),
        'mae_gain': float((mae_naive - mae) / mae_naive),
        'dir_acc': dir_acc, 'dir_base': float(base_dir),
        'dir_margin': dir_acc - float(base_dir),
        'corr': corr,
        'period': f"{str(mt['trade_date'].min())[:10]} ~ {str(mt['trade_date'].max())[:10]}",
    }


def main():
    print('載入面板（個股 + 美股 + 夜盤）…')
    panel = load_panel()
    print(f'{len(panel):,} 筆 / {panel["stock_id"].nunique()} 檔')
    print(f'夜盤特徵可用比例 {panel["night_ret"].notna().mean():.1%}、'
          f'美股 {panel.get("us_SOXX", pd.Series(dtype=float)).notna().mean():.1%}\n')

    # 所有變體共用同一批樣本：取全部特徵都齊全的列
    require = sorted({c for cols in FEATURE_SETS.values() for c in cols
                      if c in panel.columns})
    n_common = panel.dropna(subset=require + ['ret']).shape[0]
    print(f'共同可用樣本 {n_common:,} 筆（所有變體一律跑在這批上）')
    print('')

    rows = []
    for label, cols in FEATURE_SETS.items():
        have = [c for c in cols if c in panel.columns]
        if len(have) < len(cols):
            print(f'  {label}：缺少欄位，跳過')
            continue
        print(f'  訓練 {label}（{len(cols)} 特徵）…', flush=True)
        r = run_variant(label, have, panel, require)
        rows.append(r)
        if r.get('skip'):
            print(f'    {r["skip"]}')
        else:
            print(f"    MAE {r['mae']:.5f}（天真 {r['mae_naive']:.5f}，"
                  f"改善 {r['mae_gain']:+.2%}）　方向 {r['dir_acc']:.2%}"
                  f"（多數類別 {r['dir_base']:.2%}，{r['dir_margin']:+.2%}）"
                  f"　相關 {r['corr']:+.4f}")

    write_report(rows)
    return rows


def write_report(rows):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'exog_experiment.md')
    ok = [r for r in rows if not r.get('skip')]
    best = max(ok, key=lambda r: r['dir_margin']) if ok else None
    lines = [
        '# 外生特徵實驗：美股隔夜與台指期夜盤（Iteration 28）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        '**目標：** 明日報酬率（不是價格——預測價格只要複製今天收盤就有低 MAE，'
        '看起來準卻毫無資訊，Iteration 11 的十個模型就是栽在這裡）',
        '**切分：** 時序 70/15/15，訓練集全部早於測試集',
        '**樣本：** 所有變體跑在同一批（所有特徵都齊全的列）。'
        '夜盤 2018 才有、股價回溯到 1992，不對齊的話比的是資料量而不是特徵——'
        '天真基準 MAE 會跟著變動，那就是沒對齊的徵兆。',
        '',
        '| 特徵組合 | 特徵數 | MAE | 天真基準 MAE | MAE 改善 | 方向準確率 | 多數類別基準 | 超越基準 | 相關 |',
        '|---------|-------|-----|------------|---------|-----------|------------|---------|------|',
    ]
    for r in ok:
        mark = '**' if r is best else ''
        lines.append(f"| {mark}{r['label']}{mark} | {r['n_features']} | {r['mae']:.5f} | "
                     f"{r['mae_naive']:.5f} | {r['mae_gain']:+.2%} | {r['dir_acc']:.2%} | "
                     f"{r['dir_base']:.2%} | {r['dir_margin']:+.2%} | {r['corr']:+.4f} |")
    if best:
        lines += [
            '',
            f"**最佳：{best['label']}**（超越多數類別基準 {best['dir_margin']:+.2%}）",
            f"測試期間 {best['period']}、{best['n_test']:,} 筆。",
            '',
            '## 判讀',
            '',
            '「超越基準」是唯一該看的欄位。方向準確率 52% 聽起來還行，'
            '但若同期一律猜漲就有 53%，這個模型是負貢獻——'
            'Iteration 11、12 已經把這件事驗證過兩次。',
        ]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'\n報告已寫入 {path}')


if __name__ == '__main__':
    main()
