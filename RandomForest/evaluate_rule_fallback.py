"""
M3 規則 fallback 檢驗（Iteration 9）

model3_chip.py 在 RF 無法推論時（例如該股沒有價格資料）會退回規則引擎，
而規則引擎的訊號**從未被驗證過**，卻以與 RF 相同的 ±0.33 權重進入投票。

本腳本在 22 檔追蹤股票的完整歷史上重現規則邏輯，量測其方向準確率，
判斷這條 fallback 路徑是否安全。

規則（_rule_signal，近 5 日）：
    近5日買超天數>=3 且 外資5日淨額>0  → Buy
    近5日賣超天數>=3 且 外資5日淨額<0  → Sell
    否則依外資5日淨額正負            → Buy / Sell
    外資淨額為 0                     → Hold

用法：python evaluate_rule_fallback.py
產出：results/m3_rule_fallback.md
"""

import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

CRAWLER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Crawler')
sys.path.insert(0, CRAWLER_DIR)

from train_m3 import load_dataset, LABEL_HORIZON   # noqa: E402

REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'results', 'm3_rule_fallback.md')


def rule_signals(raw: pd.DataFrame) -> pd.DataFrame:
    """逐股票重現規則引擎，並接上未來報酬。"""
    out = []
    for sid, g in raw.groupby('stock_id'):
        g = g.sort_values('trade_date').reset_index(drop=True).copy()
        for c in ('foreign_net', 'total_net'):
            g[c] = pd.to_numeric(g[c], errors='coerce').fillna(0.0)
        g['close'] = pd.to_numeric(g['close'], errors='coerce')

        buy_days  = (g['total_net'] > 0).rolling(5).sum()
        sell_days = (g['total_net'] < 0).rolling(5).sum()
        f5 = g['foreign_net'].rolling(5).sum()

        sig = np.select(
            [(buy_days >= 3) & (f5 > 0), (sell_days >= 3) & (f5 < 0), f5 > 0, f5 < 0],
            ['Buy', 'Sell', 'Buy', 'Sell'], default='Hold')
        strong = ((buy_days >= 3) & (f5 > 0)) | ((sell_days >= 3) & (f5 < 0))

        g['signal'] = sig
        g['strong'] = strong          # 規則給高信心（0.5~0.95）的那一類
        g['fwd_ret'] = g['close'].shift(-LABEL_HORIZON) / g['close'] - 1
        out.append(g.dropna(subset=['fwd_ret']).iloc[4:])   # 前 4 列 rolling 未滿
    return pd.concat(out, ignore_index=True)


def summarize(d: pd.DataFrame, title: str) -> dict:
    act = d[d['signal'] != 'Hold']
    if act.empty:
        return {'name': title, 'n': 0}
    long_ = act['signal'] == 'Buy'
    r = act['fwd_ret'].values
    ok = np.where(long_, r > 0, r < 0)
    return {
        'name': title,
        'n': len(act),
        'dir_acc': float(ok.mean()),
        'n_buy': int(long_.sum()),
        'buy_dir_acc': float(ok[long_.values].mean()) if long_.any() else np.nan,
        'buy_avg_ret': float(r[long_.values].mean()) if long_.any() else np.nan,
        'n_sell': int((~long_).sum()),
        'sell_dir_acc': float(ok[~long_.values].mean()) if (~long_).any() else np.nan,
        'sell_avg_ret': float(-r[~long_.values].mean()) if (~long_).any() else np.nan,
    }


def main():
    print('載入資料…')
    raw = load_dataset()
    d = rule_signals(raw)
    print(f'{len(d)} 筆（{d["stock_id"].nunique()} 檔）')
    print('訊號分布：', d['signal'].value_counts().to_dict())

    rows = [
        summarize(d, '全部規則訊號'),
        summarize(d[d['strong']], '僅「連續買/賣超」高信心訊號'),
        summarize(d[d['trade_date'] >= d['trade_date'].quantile(0.5)], '僅近半期間'),
    ]
    print()
    for r in rows:
        if not r['n']:
            continue
        print(f"{r['name']}：出手 {r['n']} 次　方向準確率 {r['dir_acc']:.2%}")
        print(f"  買 {r['n_buy']} 次 {r['buy_dir_acc']:.2%} 平均 {r['buy_avg_ret']:+.2%}"
              f"　賣 {r['n_sell']} 次 {r['sell_dir_acc']:.2%} 平均 {r['sell_avg_ret']:+.2%}")

    lines = [
        '# M3 規則 fallback 檢驗（Iteration 9）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**資料：** {len(d)} 筆 / {d["stock_id"].nunique()} 檔追蹤股票全歷史',
        f'**標籤：** 未來 {LABEL_HORIZON} 日原始報酬方向',
        '',
        '> RF 無法推論時（該股無價格資料等）會退回規則引擎，且以相同的 ±0.33 權重',
        '> 進入投票。本表檢驗這條路徑是否安全。',
        '',
        '| 情境 | 出手次數 | 方向準確率 | 買進次數 | 買進準確率 | 買進平均報酬 | 賣出次數 | 賣出準確率 | 賣出平均報酬 |',
        '|------|---------|-----------|---------|-----------|-------------|---------|-----------|-------------|',
    ]
    for r in rows:
        if not r['n']:
            continue
        lines.append(
            f"| {r['name']} | {r['n']} | **{r['dir_acc']:.2%}** | {r['n_buy']} | "
            f"{r['buy_dir_acc']:.2%} | {r['buy_avg_ret']:+.2%} | {r['n_sell']} | "
            f"{r['sell_dir_acc']:.2%} | {r['sell_avg_ret']:+.2%} |"
        )
    lines += [
        '',
        '## 注意',
        '',
        '此檢驗**在 22 檔追蹤股票上進行**，但規則 fallback 實際觸發的場合，',
        '正是那些資料稀少、連價格都沒有的非追蹤股票——那裡的表現只會更差，',
        '本表可視為規則引擎的**樂觀上界**。',
    ]
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'\n報告已寫入 {REPORT_PATH}')


if __name__ == '__main__':
    main()
