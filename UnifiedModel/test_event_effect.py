"""
事件對振幅的原始效應量測（Iteration 20）
────────────────────────────────────────
事件特徵加進振幅模型後只帶來 +0.0011 的排序相關提升（雜訊等級）。
在下「事件沒用」的結論之前，先直接量測**原始效應**——
Iteration 15 的教訓：「加了特徵沒變好」不等於「兩者無關」，
可能是效應真實存在但已被其他特徵捕捉。

三個問題：
  A 事件窗內的振幅真的比較大嗎？（原始效應）
  B 若是，幅度多大？是否足以構成可用的訊號？
  C 若效應存在卻對模型沒幫助，是被什麼特徵捕捉了？

用法：python test_event_effect.py
產出：results/event_effect.md
"""

import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'Crawler'))

from train_range import load_data, HORIZON   # noqa: E402
from event_features import add_event_features   # noqa: E402

RESULTS_DIR = os.path.join(BASE_DIR, 'results')


def bucket_stats(d: pd.DataFrame, col: str, label: str) -> list:
    """依某個事件距離欄位分組，看實際振幅。"""
    rows = []
    overall = d['range_5d'].mean()
    for lo, hi, name in [(0, 2, '0~2 天'), (3, 5, '3~5 天'),
                         (6, 10, '6~10 天'), (11, 999, '11 天以上')]:
        sub = d[(d[col] >= lo) & (d[col] <= hi)]
        if len(sub) < 100:
            continue
        m = sub['range_5d'].mean()
        se = sub['range_5d'].std() / np.sqrt(len(sub))
        rows.append({'group': label, 'bucket': name, 'n': len(sub),
                     'mean_range': m, 'se': se,
                     'ratio': m / overall if overall else 1.0,
                     't': (m - overall) / se if se > 0 else 0.0})
    return rows


def main():
    print('載入資料…')
    d = add_event_features(load_data())
    d = d.dropna(subset=['range_5d']).reset_index(drop=True)
    overall = d['range_5d'].mean()
    print(f'樣本 {len(d)} 筆　全體平均振幅 {overall:.2%}\n')

    rows = []
    rows += bucket_stats(d, 'days_to_revenue', '距營收公布日')
    rows += bucket_stats(d, 'days_since_revenue', '營收公布後')
    rows += bucket_stats(d, 'days_to_exdiv', '距除權息日')
    rows += bucket_stats(d, 'days_since_exdiv', '除權息後')

    print(f"{'分組':16} {'區間':12} {'樣本':>8} {'平均振幅':>9} "
          f"{'vs 全體':>8} {'t 值':>8}")
    print('-' * 68)
    for r in rows:
        print(f"{r['group']:16} {r['bucket']:12} {r['n']:8} "
              f"{r['mean_range']:8.2%} {r['ratio']:7.3f}× {r['t']:+8.2f}")

    # 事件窗 vs 非事件窗的直接對比
    print()
    for col, name in (('revenue_window', '營收公布 ±2 日'),
                      ('exdiv_window', '除權息 ±2 日')):
        a = d[d[col] == 1]['range_5d']
        b = d[d[col] == 0]['range_5d']
        if len(a) < 50:
            continue
        se = np.sqrt(a.var() / len(a) + b.var() / len(b))
        diff = a.mean() - b.mean()
        print(f"{name}：窗內 {a.mean():.2%}（n={len(a)}） vs "
              f"窗外 {b.mean():.2%}（n={len(b)}）　"
              f"差異 {diff:+.3%}（t = {diff / se:+.2f}）")

    write_report(rows, d, overall)


def write_report(rows, d, overall):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'event_effect.md')
    lines = [
        '# 事件對振幅的原始效應（Iteration 20）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**樣本：** {len(d)} 筆　**全體平均振幅：** {overall:.2%}',
        '',
        '> 事件特徵對模型只有 +0.0011 的排序相關提升（雜訊等級）。',
        '> 本表直接量測原始效應，判斷是「效應不存在」還是「效應已被其他特徵捕捉」。',
        '',
        '| 分組 | 區間 | 樣本數 | 平均振幅 | vs 全體 | t 值 |',
        '|------|------|-------|---------|--------|------|',
    ]
    for r in rows:
        lines.append(f"| {r['group']} | {r['bucket']} | {r['n']} | "
                     f"{r['mean_range']:.2%} | {r['ratio']:.3f}× | {r['t']:+.2f} |")
    lines += [
        '',
        '## 解讀',
        '',
        '- **比值接近 1.0** 代表該事件窗的振幅與全體無異，事件本身沒有預測價值。',
        '- **比值明顯偏離且 t 值大** 才代表效應真實存在。',
        '- 若效應存在卻無助於模型，通常是已被既有特徵（近期波動、量能）捕捉——',
        '  事件推升波動，而波動本身已在特徵裡。',
    ]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'\n報告已寫入 {path}')


if __name__ == '__main__':
    main()
