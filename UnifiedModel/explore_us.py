"""
美股可預測性探測（Iteration 32）
────────────────────────────────
「做一個預測美股的模型」不是一個題目，是四個——而它們的難度天差地遠。
本腳本一次量測四個目標，讓資料決定哪一個值得做成模型：

    y_gap        D 日開盤 ÷ D−1 收盤 − 1     開盤跳空
    y_intraday   D 日收盤 ÷ D 日開盤 − 1     盤中（唯一整段可交易的）
    y_ret        D 日收盤 ÷ D−1 收盤 − 1     全日
    fwd_vol5     未來 5 日已實現波動率        風險量級

台股那邊的結論是「跳空可預測、方向不可預測、波動率可預測」（Iteration 11/13/16）。
美股是不是同一回事，要量過才知道，不能假設。

## 每個目標都要有天真基準，而且是強基準

    跳空／盤中／全日   方向：**多數類別**（美股長期上漲，猜漲的準確率本來就 >50%）
                      量級：前一日同項目（持續性）、以及 0
    波動率            EWMA(λ=0.94)，比較 QLIKE

沒有基準的準確率毫無意義——這是本專案反覆踩過的坑（Iteration 11、29）。

## 消融：台股資訊對美股有沒有增量

跳空模型（Iteration 16）證明美股 D−1 能預測台股 D 的開盤跳空。
反過來呢？台股 D 日盤在美股 D 開盤前 8 小時就收了，資訊上完全合法。
變體：

    us          只有美股自身與大盤（own+usmkt+cs）
    us+tw       加台股當日日盤
    us+tw+asia  再加韓日當日收盤
    全部        再加台指期日盤（**只有日盤**；夜盤涵蓋美股盤中，用了就是洩漏）

消融一律跑在同一批樣本上（`align` 取所有變體都完整的列），
否則比的是資料量不是特徵——Iteration 28 的教訓。

用法：
    python explore_us.py                 # 四個目標 × 四個變體
    python explore_us.py --targets gap   # 只跑跳空
產出：results/us_exploration.md
"""

import argparse
import logging
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'Crawler'))

RESULTS_DIR = os.path.join(BASE_DIR, 'results')

VARIANTS = {
    'us':          ['own', 'usmkt', 'cs'],
    'us+tw':       ['own', 'usmkt', 'cs', 'tw'],
    'us+tw+asia':  ['own', 'usmkt', 'cs', 'tw', 'asia'],
    '全部(含台指期日盤)': ['own', 'usmkt', 'cs', 'tw', 'asia', 'twfut'],
}

TARGETS = {
    'gap':      {'col': 'y_gap', 'baseline': 'own_gap_prev', 'kind': 'level',
                 'label': '開盤跳空 D開/D-1收'},
    'intraday': {'col': 'y_intraday', 'baseline': 'own_intraday_prev', 'kind': 'level',
                 'label': '盤中 D收/D開'},
    'ret':      {'col': 'y_ret', 'baseline': 'own_ret1', 'kind': 'level',
                 'label': '全日 D收/D-1收'},
    'vol':      {'col': 'fwd_vol5', 'baseline': 'ewma_vol', 'kind': 'vol',
                 'label': '未來 5 日已實現波動率'},
    # 5 日視窗的實現波動本身雜訊極大（5 個報酬算標準差）。台股那邊用的是 20 日，
    # 兩個一起測才分得出「美股波動率不可預測」與「5 日視窗太短」哪個才是真的。
    'vol20':    {'col': 'fwd_vol20', 'baseline': 'ewma_vol', 'kind': 'vol',
                 'label': '未來 20 日已實現波動率'},
}

PARAMS = dict(max_iter=300, learning_rate=0.05, max_depth=5,
              min_samples_leaf=80, l2_regularization=1.0, random_state=42)

EMBARGO = {'gap': 1, 'intraday': 1, 'ret': 1, 'vol': 5, 'vol20': 20}   # 標籤期封存的交易日數


def qlike(actual, pred):
    a2 = np.maximum(actual, 1e-8) ** 2
    p2 = np.maximum(pred, 1e-8) ** 2
    return float(np.mean(np.log(p2) + a2 / p2))


def _fold_bounds(dates, n_folds, start_frac=0.5):
    start = int(len(dates) * start_frac)
    return np.linspace(start, len(dates), n_folds + 1).astype(int)


def evaluate(d, cols, target, n_folds=4):
    """擴張視窗走查。回傳每折的模型與基準指標。"""
    spec = TARGETS[target]
    ycol, bcol, kind = spec['col'], spec['baseline'], spec['kind']
    log_target = kind == 'vol'
    dates = np.sort(d['trade_date'].unique())
    bounds = _fold_bounds(dates, n_folds)
    out = []
    for i in range(n_folds):
        lo, hi = dates[bounds[i]], dates[bounds[i + 1] - 1]
        te = (d['trade_date'] >= lo) & (d['trade_date'] <= hi)
        # 標籤期封存：訓練集要退到「標籤已經實現」的日期之前
        tr = d['trade_date'] < dates[max(bounds[i] - EMBARGO[target], 0)]
        if tr.sum() < 2000 or te.sum() < 200:
            continue
        y_tr = d.loc[tr, ycol].values
        m = HistGradientBoostingRegressor(**PARAMS)
        m.fit(d.loc[tr, cols].values,
              np.log(np.maximum(y_tr, 1e-6)) if log_target else y_tr)
        p = m.predict(d.loc[te, cols].values)
        pred = np.exp(p) if log_target else p
        act = d.loc[te, ycol].values
        base = d.loc[te, bcol].values
        ok = np.isfinite(pred) & np.isfinite(act) & np.isfinite(base)
        pred, act, base = pred[ok], act[ok], base[ok]
        if len(pred) < 100:
            continue

        row = {'fold': i + 1, 'from': str(lo)[:10], 'to': str(hi)[:10],
               'n_test': int(len(pred)),
               'corr': float(np.corrcoef(pred, act)[0, 1]),
               'base_corr': float(np.corrcoef(base, act)[0, 1]),
               'mae': float(np.mean(np.abs(pred - act))),
               'base_mae': float(np.mean(np.abs(base - act)))}
        if kind == 'vol':
            row['qlike'] = qlike(act, pred)
            row['base_qlike'] = qlike(act, base)
            la, lp = np.log(np.maximum(act, 1e-8)), np.log(np.maximum(pred, 1e-8))
            row['r2_log'] = float(1 - np.var(la - lp) / np.var(la))
        else:
            up = act > 0
            row['dir_acc'] = float(np.mean((pred > 0) == up))
            # 天真基準＝多數類別。美股長期上漲，猜「一律看漲」本來就贏 50%
            row['dir_base'] = float(max(up.mean(), 1 - up.mean()))
            row['zero_mae'] = float(np.mean(np.abs(act)))
        out.append(row)
    return out


def weighted(folds, key):
    w = np.array([f['n_test'] for f in folds], float)
    return float(np.sum([f[key] for f in folds] * w) / w.sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--targets', nargs='+', default=list(TARGETS))
    ap.add_argument('--folds', type=int, default=4)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    import us_panel

    all_blocks = VARIANTS['全部(含台指期日盤)']
    print('建立美股面板…')
    panel = us_panel.build(blocks=all_blocks)
    if panel.empty:
        print('面板是空的——先跑 python Crawler/backfill_us.py')
        return

    report = {}
    for tgt in args.targets:
        spec = TARGETS[tgt]
        d = us_panel.align(panel, all_blocks,
                           extra_required=[spec['col'], spec['baseline']])
        print(f"\n══ {tgt}（{spec['label']}）　共同樣本 {len(d):,} 列　"
              f"{d.trade_date.min().date()} ~ {d.trade_date.max().date()}")
        rows = []
        for vname, blocks in VARIANTS.items():
            cols = [c for c in us_panel.columns_for(blocks) if c in d.columns]
            folds = evaluate(d, cols, tgt, args.folds)
            if not folds:
                continue
            r = {'variant': vname, 'n_features': len(cols),
                 'corr': weighted(folds, 'corr'),
                 'base_corr': weighted(folds, 'base_corr'),
                 'mae': weighted(folds, 'mae'),
                 'base_mae': weighted(folds, 'base_mae'),
                 'n_test': int(sum(f['n_test'] for f in folds)),
                 'folds': folds}
            if spec['kind'] == 'vol':
                r.update(qlike=weighted(folds, 'qlike'),
                         base_qlike=weighted(folds, 'base_qlike'),
                         r2_log=weighted(folds, 'r2_log'))
                print(f"  {vname:<20} 特徵{r['n_features']:>3}　相關 {r['corr']:.4f}"
                      f"（EWMA {r['base_corr']:.4f}）　QLIKE {r['qlike']:.4f}"
                      f"（EWMA {r['base_qlike']:.4f}）　R²(log) {r['r2_log']:+.3f}")
            else:
                r.update(dir_acc=weighted(folds, 'dir_acc'),
                         dir_base=weighted(folds, 'dir_base'),
                         zero_mae=weighted(folds, 'zero_mae'))
                print(f"  {vname:<20} 特徵{r['n_features']:>3}　相關 {r['corr']:.4f}"
                      f"（持續性 {r['base_corr']:+.4f}）　方向 {r['dir_acc']*100:.2f}%"
                      f"（多數類別 {r['dir_base']*100:.2f}%）　"
                      f"MAE {r['mae']*100:.3f}%（猜 0：{r['zero_mae']*100:.3f}%）")
            rows.append(r)
        report[tgt] = {'n_rows': len(d), 'rows': rows,
                       'from': str(d.trade_date.min())[:10],
                       'to': str(d.trade_date.max())[:10]}

    write_report(report)


def write_report(report):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'us_exploration.md')
    L = ['# 美股可預測性探測（Iteration 32）', '',
         f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
         '**驗證：** 擴張視窗走查 + 標籤期封存；四個變體跑在同一批共同樣本上', '']
    for tgt, blk in report.items():
        spec = TARGETS[tgt]
        L += [f"## {tgt}：{spec['label']}", '',
              f"樣本 {blk['n_rows']:,} 列（{blk['from']} ~ {blk['to']}）", '']
        if spec['kind'] == 'vol':
            L += ['| 變體 | 特徵 | 相關 | EWMA 相關 | QLIKE | EWMA QLIKE | R²(log) |',
                  '|------|-----|------|----------|-------|-----------|---------|']
            for r in blk['rows']:
                L.append(f"| {r['variant']} | {r['n_features']} | {r['corr']:.4f} | "
                         f"{r['base_corr']:.4f} | {r['qlike']:.4f} | "
                         f"{r['base_qlike']:.4f} | {r['r2_log']:+.3f} |")
        else:
            L += ['| 變體 | 特徵 | 相關 | 持續性基準 | 方向 | 多數類別 | MAE | 猜 0 的 MAE |',
                  '|------|-----|------|-----------|------|---------|-----|-----------|']
            for r in blk['rows']:
                L.append(f"| {r['variant']} | {r['n_features']} | {r['corr']:.4f} | "
                         f"{r['base_corr']:+.4f} | {r['dir_acc']*100:.2f}% | "
                         f"{r['dir_base']*100:.2f}% | {r['mae']*100:.3f}% | "
                         f"{r['zero_mae']*100:.3f}% |")
        L.append('')
        best = max(blk['rows'], key=lambda r: r['corr']) if blk['rows'] else None
        if best:
            L += ['<details><summary>逐折（最佳變體：'
                  f"{best['variant']}）</summary>", '',
                  '| 折 | 測試期 | 測試列 | 相關 | 基準相關 |',
                  '|----|--------|-------|------|---------|']
            for f in best['folds']:
                L.append(f"| {f['fold']} | {f['from']} ~ {f['to']} | {f['n_test']:,} | "
                         f"{f['corr']:.4f} | {f['base_corr']:+.4f} |")
            L += ['', '</details>', '']
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))
    print(f'\n報告已寫入 {path}')


if __name__ == '__main__':
    main()
