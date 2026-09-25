"""
開盤跳空預測（Iteration 16）
────────────────────────────
Iteration 15 量測到：美股隔夜與台股**開盤跳空**相關高達 +0.66
（費半 ETF 可解釋約 44% 的變異），但盤中只剩 −0.13。
亦即美股資訊在開盤瞬間被完全吸收——這正是它對「收盤到收盤」預測無用的原因，
卻也代表**開盤跳空本身是高度可預測的**。

本模型預測「明日開盤 ÷ 今日收盤 − 1」，定位是**盤前參考資訊**，不是買賣訊號：
    · 跳空發生在開盤那一刻，事後無法交易
    · 用途是讓使用者知道「今晚美股這樣走，明天大概開在哪」
    · 同時供風險模組使用——預期大幅跳空時，停損距離必須把它算進去

必須勝過的基準（否則模型沒有存在價值）：
    零跳空      永遠預測 0（跳空的無條件期望值接近 0）
    費半單變量  只用 SOXX 隔夜漲幅做線性迴歸——最強的單一預測因子
    大盤平均    先預測大盤平均跳空，再套用到每檔（忽略個股差異）

用法：
    python train_gap.py
產出：
    saved_models/gap_model.joblib（需勝過全部基準才部署）
    results/gap_model.md
"""

import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'Crawler'))

from us_features import build_us_daily, LOAD_US_SQL, US_FEATURES   # noqa: E402
from night_features import attach as attach_night, NIGHT_FEATURES  # noqa: E402
from intl_features import attach as attach_intl, INTL_FEATURES      # noqa: E402

RESULTS_DIR = os.path.join(BASE_DIR, 'results')
MODEL_DIR = os.path.join(BASE_DIR, 'saved_models')
N_FOLDS = 5

TW_SQL = """
    SELECT stock_id, trade_date, open_price AS open, high_price AS high,
           low_price AS low, close_price AS close,
           COALESCE(adj_close, close_price) AS adj_close, volume
    FROM stock_daily_prices
    WHERE close_price > 0 AND open_price > 0
    ORDER BY stock_id, trade_date
"""

# 個股自身特徵：跳空幅度會隨個股波動度放大，故需要規模資訊
SELF_FEATURES = ['own_vol_20d', 'own_gap_std20', 'own_ret_1d',
                 'own_gap_ma5', 'own_beta_proxy']


DIVIDEND_SQL = """
    SELECT stock_id, ex_date, before_price, reference_price, dividend, dividend_type
    FROM stock_dividend_result
    WHERE reference_price > 0
"""


def load_dataset(adjust_dividend: bool = True) -> pd.DataFrame:
    """
    adjust_dividend=True 時，除權息日改以**除權息參考價**為基準計算跳空與報酬。

    除權息日的價格缺口是配息／配股造成的機械性結果，與美股隔夜走勢無關。
    實測 479 筆事件的平均機械性缺口：配息 3.57%、權息 8.91%，極端達 20.8%——
    而模型的 MAE 只有 0.66%，這些等於 30 倍大的離群值。
    """
    from db.connection import get_conn
    with get_conn() as conn:
        tw = pd.read_sql(TW_SQL, conn)
        raw_us = pd.read_sql(LOAD_US_SQL, conn)
        div = pd.read_sql(DIVIDEND_SQL, conn) if adjust_dividend else pd.DataFrame()

    tw['trade_date'] = pd.to_datetime(tw['trade_date'])
    tw = tw.sort_values(['stock_id', 'trade_date'])
    g = tw.groupby('stock_id')

    prev_close = g['close'].shift(1)

    # 除權息日：把「前一日收盤」換成交易所計算的除權息參考價
    tw['is_ex_div'] = False
    if not div.empty:
        div['ex_date'] = pd.to_datetime(div['ex_date'])
        tw = tw.merge(
            div[['stock_id', 'ex_date', 'reference_price']],
            left_on=['stock_id', 'trade_date'],
            right_on=['stock_id', 'ex_date'], how='left',
        )
        tw['is_ex_div'] = tw['reference_price'].notna()
        prev_close = tw['reference_price'].fillna(prev_close)
        tw = tw.drop(columns=['ex_date', 'reference_price'])

    tw['prev_base'] = prev_close
    tw['gap'] = tw['open'] / prev_close - 1          # ← 預測目標（已扣除機械性缺口）
    # 個股報酬改用 adj_close（Iteration 18：已還原除權息**與減資**，
    # 涵蓋範圍比原本的除權息查表法更完整）
    tw['own_ret_1d'] = g['adj_close'].transform(lambda s: s.pct_change())

    daily_ret = tw['own_ret_1d']
    tw['own_vol_20d'] = daily_ret.groupby(tw['stock_id']).transform(
        lambda s: s.rolling(20).std())
    # 只用「過去」的跳空統計，避免用到當日目標
    tw['own_gap_std20'] = tw.groupby('stock_id')['gap'].transform(
        lambda s: s.shift(1).rolling(20).std())
    tw['own_gap_ma5'] = tw.groupby('stock_id')['gap'].transform(
        lambda s: s.shift(1).rolling(5).mean())

    # beta 代理：個股波動 ÷ 全體平均波動，衡量該股對市場衝擊的放大倍數
    mkt_vol = tw.groupby('trade_date')['own_vol_20d'].transform('mean')
    tw['own_beta_proxy'] = tw['own_vol_20d'] / (mkt_vol + 1e-9)

    us = build_us_daily(raw_us)
    merged = pd.merge_asof(
        tw.sort_values('trade_date'), us.sort_values('us_date'),
        left_on='trade_date', right_on='us_date',
        direction='backward', allow_exact_matches=False,   # 嚴格早於台股日期
    )
    merged['us_gap_days'] = (merged['trade_date'] - merged['us_date']).dt.days

    # 台指期夜盤（Iteration 28）。時序上它領先同日開盤，故用同一個 trade_date 對齊；
    # 當日日盤的欄位一概不碰——那是開盤之後才知道的事。
    merged = attach_night(merged, 'TX')

    # 韓股／日股（Iteration 29）。它們比台股早一小時開盤，**當日開盤價**在
    # 台股開盤前就知道；**當日收盤價**（台北 14:00~14:30）則在台股收盤之後，
    # 一律不取用——intl_features 只產出符合時序的欄位。
    merged = attach_intl(merged)

    return merged.sort_values(['trade_date', 'stock_id']).reset_index(drop=True)


def folds(data: pd.DataFrame):
    dates = np.sort(data['trade_date'].unique())
    start = int(len(dates) * 0.5)
    bounds = np.linspace(start, len(dates), N_FOLDS + 1).astype(int)
    for i in range(N_FOLDS):
        te_lo, te_hi = dates[bounds[i]], dates[bounds[i + 1] - 1]
        tr = (data['trade_date'] < te_lo).values          # 跳空為當日事件，無需封存
        te = ((data['trade_date'] >= te_lo) &
              (data['trade_date'] <= te_hi)).values
        if tr.sum() > 1000 and te.sum() > 100:
            yield tr, te


def evaluate(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    err = y_true - y_pred
    ss_res = float(np.sum(err ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    return {
        'corr': float(np.corrcoef(y_pred, y_true)[0, 1]) if y_pred.std() > 0 else 0.0,
        'r2': 1 - ss_res / ss_tot if ss_tot > 0 else 0.0,
        'mae': float(np.mean(np.abs(err))),
        'rmse': float(np.sqrt(np.mean(err ** 2))),
        'dir_acc': float(np.mean(np.sign(y_pred) == np.sign(y_true))),
        'n': int(len(y_true)),
    }


def run_once(adjust_dividend: bool, label: str) -> dict:
    """跑一次完整流程；adjust_dividend 控制是否扣除除權息的機械性缺口。"""
    data = load_dataset(adjust_dividend=adjust_dividend)
    us_cols = [c for c in US_FEATURES if c in data.columns]
    night_cols = [c for c in NIGHT_FEATURES if c in data.columns]
    cols = us_cols + night_cols + SELF_FEATURES
    d = data[data[cols + ['gap']].notna().all(axis=1)].reset_index(drop=True)

    from sklearn.ensemble import HistGradientBoostingRegressor
    X, y = d[cols].values, d['gap'].values
    preds, trues = [], []
    for tr, te in folds(d):
        reg = HistGradientBoostingRegressor(
            max_iter=400, max_depth=5, learning_rate=0.05, min_samples_leaf=60,
            l2_regularization=1.0, early_stopping=True,
            validation_fraction=0.15, random_state=42)
        reg.fit(X[tr], y[tr])
        preds.append(reg.predict(X[te]))
        trues.append(y[te])
    m = evaluate(np.concatenate(trues), np.concatenate(preds))
    m['label'] = label
    n_ex = int(d['is_ex_div'].sum()) if 'is_ex_div' in d else 0
    m['n_ex_div'] = n_ex
    print(f"  {label:20} 相關={m['corr']:.4f} R²={m['r2']:+.4f} "
          f"MAE={m['mae']:.4%} 方向={m['dir_acc']:.2%}"
          f"（除權息日 {n_ex} 筆）")
    return m


def main():
    print('載入資料…')

    # ── 除權息修正的效果對照 ────────────────────────────────────────────
    print('\n=== 除權息修正對照 ===')
    before = run_once(False, '未修正（原版）')
    after = run_once(True, '已修正除權息')
    print(f"  → MAE {before['mae']:.4%} → {after['mae']:.4%}"
          f"（改善 {(before['mae'] - after['mae']) / before['mae']:.1%}）"
          f"　R² {before['r2']:+.4f} → {after['r2']:+.4f}")

    print('\n=== 與基準線比較（採用修正後資料）===')
    data = load_dataset(adjust_dividend=True)
    us_cols = [c for c in US_FEATURES if c in data.columns]
    # 台指期夜盤（Iteration 28 消融通過）：加入後走查相關 0.6727 → 0.6935、
    # 方向準確率 69.92% → 72.24%，超過 +0.02 的部署門檻。
    # 夜盤單獨使用（不含美股）也有 0.6851，優於美股——它是更直接的訊號，
    # 但兩者併用仍有額外提升，故都保留。
    night_cols = [c for c in NIGHT_FEATURES if c in data.columns]
    cols = us_cols + night_cols + SELF_FEATURES
    need = cols + ['gap']
    d = data[data[need].notna().all(axis=1)].reset_index(drop=True)
    print(f'可用 {len(d)} 筆 / {d["stock_id"].nunique()} 檔 '
          f'（{str(d["trade_date"].min())[:10]} ~ {str(d["trade_date"].max())[:10]}）')
    print(f'美股特徵 {len(us_cols)} 個 + 夜盤特徵 {len(night_cols)} 個 '
          f'+ 個股特徵 {len(SELF_FEATURES)} 個')
    print(f'其中除權息日 {int(d["is_ex_div"].sum())} 筆\n')

    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import LinearRegression

    X = d[cols].values
    y = d['gap'].values
    soxx = d['us_soxx_ret1'].values.reshape(-1, 1)

    preds = {k: [] for k in ('模型', '零跳空', '費半單變量', '大盤平均')}
    trues, idxs = [], []

    for tr, te in folds(d):
        # 主模型
        reg = HistGradientBoostingRegressor(
            max_iter=400, max_depth=5, learning_rate=0.05, min_samples_leaf=60,
            l2_regularization=1.0, early_stopping=True,
            validation_fraction=0.15, random_state=42)
        reg.fit(X[tr], y[tr])
        preds['模型'].append(reg.predict(X[te]))

        preds['零跳空'].append(np.zeros(te.sum()))

        # 基準：只用費半隔夜漲幅的線性迴歸
        lin = LinearRegression().fit(soxx[tr], y[tr])
        preds['費半單變量'].append(lin.predict(soxx[te]))

        # 基準：先預測大盤平均跳空，再套用到每檔（忽略個股差異）
        mkt_tr = pd.DataFrame({'d': d.loc[tr, 'trade_date'], 'g': y[tr],
                               's': soxx[tr].ravel()}).groupby('d').mean()
        lin_m = LinearRegression().fit(mkt_tr[['s']].values, mkt_tr['g'].values)
        preds['大盤平均'].append(lin_m.predict(soxx[te]))

        trues.append(y[te])
        idxs.append(np.where(te)[0])

    t = np.concatenate(trues)
    results = {}
    for k, v in preds.items():
        results[k] = evaluate(t, np.concatenate(v))

    print(f"{'方法':14} {'相關係數':>9} {'R²':>9} {'MAE':>9} {'方向準確率':>10}")
    print('-' * 56)
    for k in ('零跳空', '費半單變量', '大盤平均', '模型'):
        r = results[k]
        print(f"{k:14} {r['corr']:9.4f} {r['r2']:+9.4f} {r['mae']:9.4%} "
              f"{r['dir_acc']:10.2%}")

    model_r2 = results['模型']['r2']
    best_base = max(results[k]['r2'] for k in ('零跳空', '費半單變量', '大盤平均'))
    deploy = model_r2 > best_base
    print(f"\n模型 R²={model_r2:.4f}　最佳基準 R²={best_base:.4f}　"
          f"→ {'部署' if deploy else '**不部署**（未勝過基準）'}")

    write_report(results, len(d), len(us_cols), deploy,
                 dividend_effect=(before, after))
    if deploy:
        save_model(d, cols, X, y)


def save_model(d, cols, X, y):
    import joblib
    from sklearn.ensemble import HistGradientBoostingRegressor
    reg = HistGradientBoostingRegressor(
        max_iter=400, max_depth=5, learning_rate=0.05, min_samples_leaf=60,
        l2_regularization=1.0, early_stopping=True,
        validation_fraction=0.15, random_state=42)
    reg.fit(X, y)
    os.makedirs(MODEL_DIR, exist_ok=True)
    path = os.path.join(MODEL_DIR, 'gap_model.joblib')
    joblib.dump({'model': reg, 'feature_cols': cols,
                 'trained_at': datetime.now().isoformat(),
                 'n_train': int(len(y))}, path)
    print(f'模型已存 {path}')
    _register('gap', {'trained_at': datetime.now().isoformat()})


def write_report(results, n, n_us, deploy, dividend_effect=None):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'gap_model.md')
    lines = [
        '# 開盤跳空預測模型（Iteration 16 建立，Iteration 17 修正除權息）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**樣本：** {n} 筆　**特徵：** 美股 {n_us} 個 + 個股 {len(SELF_FEATURES)} 個',
        f'**驗證：** {N_FOLDS} 折擴張視窗走查（跳空為當日事件，標籤不跨期，無需封存）',
        '',
        '> 定位是**盤前參考資訊**，不是買賣訊號——跳空發生在開盤瞬間，事後無法交易。',
        '',
    ]
    if dividend_effect:
        b, a = dividend_effect
        lines += [
            '## 除權息修正的效果（Iteration 17）',
            '',
            '除權息日的價格缺口是配息／配股造成的機械性結果，與美股走勢無關。',
            f'改以交易所的**除權息參考價**為基準後（{a["n_ex_div"]} 筆事件）：',
            '',
            '| 版本 | 相關係數 | R² | MAE | 方向準確率 |',
            '|------|---------|-----|-----|-----------|',
            f'| {b["label"]} | {b["corr"]:.4f} | {b["r2"]:+.4f} | {b["mae"]:.4%} | {b["dir_acc"]:.2%} |',
            f'| **{a["label"]}** | **{a["corr"]:.4f}** | **{a["r2"]:+.4f}** | '
            f'**{a["mae"]:.4%}** | **{a["dir_acc"]:.2%}** |',
            '',
        ]
    lines += [
        '| 方法 | 相關係數 | R² | MAE | 方向準確率 |',
        '|------|---------|-----|-----|-----------|',
    ]
    for k in ('零跳空', '費半單變量', '大盤平均', '模型'):
        r = results[k]
        mark = '**' if k == '模型' else ''
        lines.append(f"| {mark}{k}{mark} | {r['corr']:.4f} | {r['r2']:+.4f} | "
                     f"{r['mae']:.4%} | {r['dir_acc']:.2%} |")
    lines += [
        '',
        '## 基準線說明',
        '',
        '- **零跳空**：永遠預測 0。跳空的無條件期望值接近 0，這是最基本的對照。',
        '- **費半單變量**：只用 SOXX 隔夜漲幅做線性迴歸，即 Iteration 15 找到的最強單因子。',
        '- **大盤平均**：先由 SOXX 預測大盤平均跳空，再套用到每檔，完全忽略個股差異。',
        '  模型若無法勝過它，代表個股層級的特徵沒有貢獻。',
        '',
        f'**部署判定：{"通過" if deploy else "未通過（不部署）"}**',
    ]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'報告已寫入 {path}')


def _register(model_type: str, metrics: dict):
    """
    把這次訓練登記到模型登錄表的 candidate 上（Iteration 21）。

    只影響 candidate——已凍結的長期服役版本存在 `_versions/` 底下的快照，
    訓練腳本碰不到。登錄失敗只印訊息，不影響訓練本身。
    """
    try:
        import model_registry as registry
        v = registry.register_training(model_type, train_metrics=metrics)
        if v:
            print(f'已登錄為 {model_type} v{v["version"]}（candidate）')
    except Exception as e:
        print(f'（模型登錄略過：{e}）')


if __name__ == '__main__':
    main()
