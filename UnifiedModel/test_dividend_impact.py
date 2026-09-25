"""
除權息調整對波動率模型的影響（Iteration 17）
────────────────────────────────────────────
跳空模型的改善只有 1.5%（除權息日僅佔 0.33% 樣本），
但**波動率模型受害可能更深**：

    單一 20% 的機械性跌幅落在 20 日滾動窗內，
    會把該股波動率估計推高數倍，且影響持續 20 個交易日。
    亦即一次除權息事件會汙染 20 筆樣本，而非 1 筆。

本腳本在完全相同的走查驗證下，比較「有無除權息調整」對波動率預測的影響，
並直接量化除權息事件對波動度估計的汙染程度。

用法：python test_dividend_impact.py
產出：results/dividend_impact.md
"""

import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'Crawler'))

from features import build_panel, LOAD_SQL, PRICE_FEATURES, CS_FEATURES, \
    MARKET_FEATURES   # noqa: E402
from train_volatility import add_vol_features, ewma_vol, folds, \
    EXTRA_VOL_FEATURES, score   # noqa: E402
from dividend_adj import adjusted_returns, load_dividends   # noqa: E402

RESULTS_DIR = os.path.join(BASE_DIR, 'results')
HORIZON = 20


def load_data(adjust: bool) -> pd.DataFrame:
    from db.connection import get_conn
    with get_conn() as conn:
        raw = pd.read_sql(LOAD_SQL, conn)

    panel = add_vol_features(build_panel(raw)).sort_values(['stock_id', 'trade_date'])
    panel = panel.reset_index(drop=True)

    if adjust:
        daily = adjusted_returns(panel)
    else:
        daily = panel.groupby('stock_id')['close'].transform(lambda s: s.pct_change())

    panel['daily_ret'] = daily.values
    panel['fwd_vol'] = panel.groupby('stock_id')['daily_ret'].transform(
        lambda s: s.shift(-HORIZON).rolling(HORIZON).std())
    panel['ewma_vol'] = panel.groupby('stock_id')['daily_ret'].transform(ewma_vol)
    return panel.dropna(subset=['fwd_vol', 'ewma_vol']).reset_index(drop=True)


def run(data: pd.DataFrame, cols: list) -> dict:
    from sklearn.ensemble import HistGradientBoostingRegressor
    X = data[cols].values
    y_raw = data['fwd_vol'].values
    y = np.log(np.maximum(y_raw, 1e-8))
    preds, trues = [], []
    for tr, te in folds(data, HORIZON):
        reg = HistGradientBoostingRegressor(
            max_iter=400, max_depth=5, learning_rate=0.05, min_samples_leaf=80,
            l2_regularization=1.0, early_stopping=True,
            validation_fraction=0.15, random_state=42)
        reg.fit(X[tr], y[tr])
        preds.append(np.exp(reg.predict(X[te])))
        trues.append(y_raw[te])
    return score(np.concatenate(trues), np.concatenate(preds))


def contamination_report() -> dict:
    """
    量化公司行動對波動度估計的汙染範圍。

    注意：不能用「調整前後報酬有差異的天數」來數事件——
    adj_close 會把事件**之前**的整段歷史都按比例縮放，
    那樣會把所有調整過的日子都算成事件（實測會得到 91,572 這種離譜數字）。
    正確作法是直接查公司行動表的事件日期。
    """
    from db.connection import get_conn
    with get_conn() as conn:
        raw = pd.read_sql(LOAD_SQL, conn)
        events = pd.read_sql("""
            SELECT stock_id, ex_date FROM stock_dividend_result
            UNION ALL
            SELECT stock_id, ex_date FROM stock_capital_reduction
        """, conn)
    panel = build_panel(raw).sort_values(['stock_id', 'trade_date']).reset_index(drop=True)

    unadj = panel.groupby('stock_id')['close'].transform(lambda s: s.pct_change())
    adj = adjusted_returns(panel)

    # 只計算落在面板日期範圍內的事件
    events['ex_date'] = pd.to_datetime(events['ex_date'])
    panel_dates = pd.to_datetime(panel['trade_date'])
    key = set(zip(panel['stock_id'], panel_dates))
    n_events = sum(1 for s, d in zip(events['stock_id'], events['ex_date'])
                   if (s, d) in key)
    n_contaminated = min(n_events * HORIZON, len(panel))

    # 機械性缺口只在事件當天量測
    ev_mask = pd.Series([(s, d) in set(zip(events['stock_id'], events['ex_date']))
                         for s, d in zip(panel['stock_id'], panel_dates)])
    gap_on_events = (unadj[ev_mask.values] - adj[ev_mask.values]).abs()

    return {
        'n_rows': len(panel),
        'n_events': n_events,
        'n_dividend_records': len(events),
        'n_contaminated_est': n_contaminated,
        'pct_contaminated': n_contaminated / len(panel) * 100,
        'max_mechanical_drop': float(gap_on_events.max()) if len(gap_on_events) else 0.0,
        'unadj_vol_mean': float(unadj.std()),
        'adj_vol_mean': float(adj.std()),
    }


def main():
    print('量化除權息對波動度估計的汙染…')
    c = contamination_report()
    print(f"  面板 {c['n_rows']} 筆，除權息事件 {c['n_events']} 筆")
    print(f"  單筆事件汙染其後 {HORIZON} 個交易日的滾動窗 → "
          f"估計受影響 {c['n_contaminated_est']} 筆（{c['pct_contaminated']:.2f}%）")
    print(f"  最大機械性跌幅 {c['max_mechanical_drop']:.2%}")
    print(f"  全體日報酬標準差：未調整 {c['unadj_vol_mean']:.4%} → "
          f"調整後 {c['adj_vol_mean']:.4%}")

    print('\n走查驗證對照…')
    rows = []
    for adjust, label in ((False, '未調整'), (True, '除權息調整後')):
        d = load_data(adjust)
        cols = [c2 for c2 in PRICE_FEATURES + CS_FEATURES + MARKET_FEATURES
                + EXTRA_VOL_FEATURES if c2 in d.columns]
        d = d[d[cols].notna().all(axis=1)].reset_index(drop=True)
        s = run(d, cols)
        s['label'] = label
        s['n'] = len(d)
        rows.append(s)
        print(f"  {label:14} 相關={s['corr']:.4f} R²(log)={s['r2_log']:+.4f} "
              f"QLIKE={s['qlike']:.4f}（{len(d)} 筆）")

    b, a = rows
    print(f"\n  → 相關 {b['corr']:.4f} → {a['corr']:.4f}"
          f"　R²(log) {b['r2_log']:+.4f} → {a['r2_log']:+.4f}")

    write_report(c, rows)


def write_report(c, rows):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'dividend_impact.md')
    b, a = rows
    lines = [
        '# 除權息調整對波動率模型的影響（Iteration 17）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        '',
        '## 汙染範圍量化',
        '',
        '| 項目 | 數值 |',
        '|------|------|',
        f'| 面板總筆數 | {c["n_rows"]} |',
        f'| 除權息事件 | {c["n_events"]} 筆 |',
        f'| 估計受汙染筆數（事件 × {HORIZON} 日滾動窗） | {c["n_contaminated_est"]}'
        f'（{c["pct_contaminated"]:.2f}%） |',
        f'| 最大機械性跌幅 | {c["max_mechanical_drop"]:.2%} |',
        f'| 全體日報酬標準差 | {c["unadj_vol_mean"]:.4%} → {c["adj_vol_mean"]:.4%} |',
        '',
        '> 關鍵：一次除權息事件會汙染其後 **20 個交易日**的滾動波動度估計，',
        '> 而非只影響當天一筆。這是它對波動率模型的影響大於跳空模型的原因。',
        '',
        '## 波動率預測走查對照',
        '',
        '| 版本 | 樣本 | 相關係數 | R²(log) | QLIKE |',
        '|------|------|---------|---------|-------|',
        f'| {b["label"]} | {b["n"]} | {b["corr"]:.4f} | {b["r2_log"]:+.4f} | {b["qlike"]:.4f} |',
        f'| **{a["label"]}** | {a["n"]} | **{a["corr"]:.4f}** | **{a["r2_log"]:+.4f}** | '
        f'**{a["qlike"]:.4f}** |',
    ]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'\n報告已寫入 {path}')


if __name__ == '__main__':
    main()
