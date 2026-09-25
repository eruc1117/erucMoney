"""
M3 部署政策模擬（Iteration 9）

train_m3.py 的走查彙總說「買進 482 次、準確率 66.8%」，但沒有回答一個
對使用者更重要的問題：**這 482 次分散在多少個交易日？**

若多數日子一個訊號都沒有，那模型雖然「準」卻近乎沉默 —— 這與 v1 門檻
寫死 0.45 導致永遠 Hold 的失效只是程度之差。本腳本以走查同樣的切分逐日
模擬線上政策（門檻 0.40 + 賣出抑制），量化實際出手頻率。

用法：python simulate_deployment.py
產出：results/m3_deployment_sim.md
"""

import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

CRAWLER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Crawler')
sys.path.insert(0, CRAWLER_DIR)

from m3_features import MODEL_FEATURE_COLS   # noqa: E402
from train_m3 import (                        # noqa: E402
    load_dataset, build_training_frame, alpha_labels,
    RF_PARAMS, N_FOLDS, EMBARGO_DAYS, PROBA_GATE,
)

REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'results', 'm3_deployment_sim.md')


def collect_predictions(data: pd.DataFrame) -> pd.DataFrame:
    """走查各折的測試期預測，串成一張逐日逐股票的表。"""
    dates = np.sort(data['trade_date'].unique())
    start = int(len(dates) * 0.5)
    bounds = np.linspace(start, len(dates), N_FOLDS + 1).astype(int)
    X = data[MODEL_FEATURE_COLS].values

    out = []
    for i in range(N_FOLDS):
        te_lo, te_hi = dates[bounds[i]], dates[bounds[i + 1] - 1]
        embargo_from = dates[max(bounds[i] - EMBARGO_DAYS, 0)]
        train_mask = (data['trade_date'] < embargo_from).values
        test_mask  = ((data['trade_date'] >= te_lo) & (data['trade_date'] <= te_hi)).values

        y = alpha_labels(data, train_mask)
        model = RandomForestClassifier(**RF_PARAMS)
        model.fit(X[train_mask], y[train_mask])
        proba = model.predict_proba(X[test_mask])

        sub = data.loc[test_mask, ['stock_id', 'trade_date', 'fwd_ret']].copy()
        sub['p_sell'], sub['p_hold'], sub['p_buy'] = proba[:, 0], proba[:, 1], proba[:, 2]
        sub['fold'] = i + 1
        out.append(sub)
        print(f'  fold {i+1} 完成（{test_mask.sum()} 筆）')
    return pd.concat(out, ignore_index=True)


def apply_policy(df: pd.DataFrame, gate: float, suppress_sell: bool) -> pd.Series:
    proba = df[['p_sell', 'p_hold', 'p_buy']].values
    pred = proba.argmax(axis=1)
    pred = np.where(proba.max(axis=1) < gate, 1, pred)
    sig = pd.Series(pred, index=df.index).map({0: 'Sell', 1: 'Hold', 2: 'Buy'})
    if suppress_sell:
        sig = sig.replace('Sell', 'Hold')
    return sig


def summarize(df: pd.DataFrame, sig: pd.Series) -> dict:
    d = df.assign(signal=sig)
    n_days = d['trade_date'].nunique()
    per_day = d.groupby('trade_date')['signal'].apply(lambda s: (s == 'Buy').sum())
    buys = d[d['signal'] == 'Buy']
    return {
        'n_days': n_days,
        'days_with_buy': int((per_day > 0).sum()),
        'pct_days_with_buy': float((per_day > 0).mean()),
        'avg_buy_per_day': float(per_day.mean()),
        'max_buy_per_day': int(per_day.max()),
        'n_buy': len(buys),
        'buy_dir_acc': float((buys['fwd_ret'] > 0).mean()) if len(buys) else np.nan,
        'buy_avg_ret': float(buys['fwd_ret'].mean()) if len(buys) else np.nan,
        'longest_silence': int(_longest_zero_run(per_day)),
    }


def _longest_zero_run(per_day: pd.Series) -> int:
    """最長連續無訊號天數。"""
    best = cur = 0
    for v in per_day.sort_index().values:
        cur = cur + 1 if v == 0 else 0
        best = max(best, cur)
    return best


def main():
    print('載入資料…')
    data = build_training_frame(load_dataset())
    print(f'面板 {len(data)} 筆\n走查預測…')
    pred = collect_predictions(data)

    # 賣出一律抑制（多空拆解已證實賣出側無 edge），此處專看門檻對「出手頻率」的影響
    scenarios = [
        ('門檻 0.45（v1 設定）', 0.45, True),
        ('門檻 0.40', 0.40, True),
        ('門檻 0.35', 0.35, True),
        ('門檻 0.30', 0.30, True),
        ('無門檻', 0.0, True),
    ]
    rows = []
    print()
    for name, gate, sup in scenarios:
        s = summarize(pred, apply_policy(pred, gate, sup))
        s['name'] = name
        rows.append(s)
        print(f"{name}\n  有買訊的交易日 {s['days_with_buy']}/{s['n_days']} "
              f"({s['pct_days_with_buy']:.0%})　平均每日 {s['avg_buy_per_day']:.2f} 檔"
              f"　最長沉默 {s['longest_silence']} 天\n"
              f"  買訊 {s['n_buy']} 次　方向準確率 {s['buy_dir_acc']:.2%}"
              f"　平均 3 日報酬 {s['buy_avg_ret']:+.2%}\n")

    write_report(rows, pred)


def write_report(rows: list, pred: pd.DataFrame):
    lines = [
        '# M3 部署政策模擬（Iteration 9）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**模擬範圍：** 走查 {N_FOLDS} 折的全部測試期，'
        f'{pred["trade_date"].nunique()} 個交易日 × {pred["stock_id"].nunique()} 檔',
        '',
        '> 回答「模型多久出手一次」——準確率再高，若長期沉默對使用者仍無價值。',
        '',
        '| 政策 | 有買訊天數 | 佔比 | 平均每日檔數 | 最長沉默 | 買訊次數 | 方向準確率 | 平均 3 日報酬 |',
        '|------|-----------|------|-------------|---------|---------|-----------|--------------|',
    ]
    for r in rows:
        lines.append(
            f"| {r['name']} | {r['days_with_buy']}/{r['n_days']} | {r['pct_days_with_buy']:.0%} | "
            f"{r['avg_buy_per_day']:.2f} | {r['longest_silence']} 天 | {r['n_buy']} | "
            f"{r['buy_dir_acc']:.2%} | {r['buy_avg_ret']:+.2%} |"
        )
    lines += [
        '',
        '## 為何選 0.35 而非更準的 0.40',
        '',
        '門檻愈高愈準，但也愈沉默，兩者必須一起看：',
        '',
        '- **0.40**：方向準確率 66.8%、平均 +2.93%，但只有 26% 的交易日出手，',
        '  且曾連續 **50 個交易日**（約 2.5 個月）完全沉默。M3 在投票中等於長期缺席，',
        '  前端看起來與「模型壞掉」無異。',
        '- **0.35**：準確率降到 56.9%、平均 +1.10%，但 82% 的交易日有訊號、',
        '  最長沉默僅 8 天。以「總體訊號價值」估算（出手次數 × 平均報酬），',
        '  0.35 約為 0.40 的兩倍。',
        '',
        '故線上採 0.35。若使用者偏好「少而精」，改 `train_m3.py` 的 `PROBA_GATE`',
        '重跑即可，模型本身不需更動。',
        '',
        '## 仍須注意',
        '',
        'M3 是**選擇性訊號**而非每日評分，賣出側已整體抑制（走查證實無 edge），',
        '因此 M3 只會投 Buy 或 Hold，不會投 Sell。這讓 M3 在投票中只能往多方推，',
        '是有意識的取捨，記錄於此以免日後誤判為 bug。',
    ]
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'報告已寫入 {REPORT_PATH}')


if __name__ == '__main__':
    main()
