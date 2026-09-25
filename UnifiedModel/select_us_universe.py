"""
美股標的清單重新檢討（Iteration 34）
────────────────────────────────────
Iteration 14 挑的 12 檔是「美股大盤＋半導體＋台股 ADR＋大型科技」的直覺清單。
Iteration 32 做出反向跳空模型後才發現：**訊號來自台灣**，所以與台股供應鏈
連動越深的標的越準（TSM 0.443、UMC 0.401），AAPL/MSFT 墊底（0.159、0.153）。
那份清單是在不知道訊號來源的情況下挑的，理應重挑。

## 候選

現行 12 檔 ＋ 11 檔與台灣連動有明確機制的標的：

    半導體設備（台積電資本支出）  ASML AMAT LRCX KLAC
    台積電代工客戶（fabless）      QCOM MRVL
    台灣公司 ADR                   ASX（日月光）HIMX（奇景）SIMO（慧榮）
    台灣指數 ETF                   EWT（iShares MSCI Taiwan）
    半導體 ETF                     SMH

EWT 要特別說：它本身就是台股，在美國時區交易——台股當日盤預測它的開盤跳空
幾乎是套套邏輯。它會很準，但那不是「預測美股」。報告裡單獨列出，不拿它撐平均。

## 為什麼要巢狀（Iteration 30 的教訓）

「用走查分數挑標的，再用同一份走查報分數」是選擇偏誤：挑得越久分數越好看。
這裡沿用 optimise_all.py 的做法：

    外層折 k：測試期 = 第 k 段（完全沒被挑選過程看過）
        └─ 內層：只在外層訓練期裡再切 2 折走查，逐檔算相關與方向，
           過門檻（相關 ≥0.15、方向贏多數類別 2pp）的才入選
        └─ 用入選清單重建面板（橫斷面特徵隨清單變）、重訓、到外層測試期評分

三個外層折各自挑出一份清單。**穩定性比分數重要**：一檔要在 ≥2/3 折被選中才留下。

## 判定

1. 新清單的模型，在**原 12 檔的列**上，外層相關不得比原清單的模型低超過 0.01
   （清單變了橫斷面特徵就變，得確認沒有拖累原本準的標的）。
2. 新增的每一檔，在最終清單的模型下，外層走查須各自過門檻。
3. 退場的標的，是在多數折的內層挑選中沒過門檻的。

用法：python select_us_universe.py [--outer 3] [--inner 2]
產出：results/us_universe.md
"""

import argparse
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'Crawler'))

import us_panel
from train_us_gap import (BLOCKS, TARGET, BASELINE, PARAMS, HORIZON,
                          DEPLOY_DIR_MARGIN, DEPLOY_MIN_CORR, _metrics)

RESULTS_DIR = os.path.join(BASE_DIR, 'results')

CURRENT = list(us_panel.TICKERS)
CANDIDATES = {
    'ASML': ('ASML Holding', 'equipment'),
    'AMAT': ('Applied Materials', 'equipment'),
    'LRCX': ('Lam Research', 'equipment'),
    'KLAC': ('KLA', 'equipment'),
    'QCOM': ('Qualcomm', 'semiconductor'),
    'MRVL': ('Marvell', 'semiconductor'),
    'ASX':  ('ASE Technology ADR', 'tw_adr'),
    'HIMX': ('Himax ADR', 'tw_adr'),
    'SIMO': ('Silicon Motion ADR', 'tw_adr'),
    'EWT':  ('iShares MSCI Taiwan ETF', 'tw_etf'),
    'SMH':  ('VanEck Semiconductor ETF', 'semiconductor'),
}
TAUTOLOGICAL = {'EWT'}          # 本身就是台股，不拿它撐平均
# 大盤參照：usmkt 與 cs 區塊的特徵（SPY 相對報酬、QQQ−SPY、SOXX 波動）由它們算出，
# 面板少了它們整張會空。所以它們一律留在清單裡，不參與退場——
# 報告照樣列出它們的成績，只是門檻不適用。
REFERENCE = ['SPY', 'QQQ', 'SOXX']
UNIVERSE = CURRENT + list(CANDIDATES)
MIN_ROWS_PER_TICKER = 50
STABILITY_MIN = 2 / 3
REGRESSION_TOL = 0.01


# ── 面板 ────────────────────────────────────────────────────────────────────
_panel_cache = {}


def build(tickers):
    """依清單建面板並對齊。橫斷面／廣度特徵隨清單變，所以每份清單都得重建。"""
    key = tuple(sorted(set(tickers) | set(REFERENCE)))
    if key not in _panel_cache:
        panel = us_panel.build(blocks=BLOCKS, tickers=list(key))
        cols = [c for c in us_panel.columns_for(BLOCKS) if c in panel.columns]
        d = us_panel.align(panel, BLOCKS, extra_required=[TARGET, BASELINE])
        _panel_cache[key] = (d.reset_index(drop=True), cols)
    return _panel_cache[key]


def fit_predict(d, cols, tr_mask, te_mask):
    m = HistGradientBoostingRegressor(**PARAMS)
    m.fit(d.loc[tr_mask, cols].values, d.loc[tr_mask, TARGET].values)
    sub = d.loc[te_mask, ['ticker', 'trade_date', TARGET, BASELINE]].copy()
    sub['pred'] = m.predict(d.loc[te_mask, cols].values)
    return sub[np.isfinite(sub['pred']) & np.isfinite(sub[TARGET]) & np.isfinite(sub[BASELINE])]


def per_ticker(sub):
    out = {}
    for tk, g in sub.groupby('ticker'):
        if len(g) < MIN_ROWS_PER_TICKER:
            continue
        r = _metrics(g['pred'].values, g[TARGET].values, g[BASELINE].values)
        r['margin'] = r['dir_acc'] - r['dir_base']
        out[tk] = r
    return out


def overall(sub, tickers=None):
    if tickers is not None:
        sub = sub[sub['ticker'].isin(tickers)]
    if sub.empty:
        return None
    r = _metrics(sub['pred'].values, sub[TARGET].values, sub[BASELINE].values)
    r['margin'] = r['dir_acc'] - r['dir_base']
    return r


def passes(r):
    return r['corr'] >= DEPLOY_MIN_CORR and r['margin'] >= DEPLOY_DIR_MARGIN


def weighted_ticker(list_of_dicts):
    """多折的逐檔指標依測試列數加權。"""
    acc = {}
    for d in list_of_dicts:
        for tk, r in d.items():
            a = acc.setdefault(tk, {'n': 0, 'corr': 0.0, 'dir_acc': 0.0, 'dir_base': 0.0})
            n = r['n_test']
            a['n'] += n
            for k in ('corr', 'dir_acc', 'dir_base'):
                a[k] += r[k] * n
    out = {}
    for tk, a in acc.items():
        n = a['n']
        out[tk] = {'n_test': n, 'corr': a['corr'] / n, 'dir_acc': a['dir_acc'] / n,
                   'dir_base': a['dir_base'] / n,
                   'margin': (a['dir_acc'] - a['dir_base']) / n}
    return out


# ── 折的切法：與 train_us_gap.walk_forward 同一套 ───────────────────────────
def fold_bounds(dates, n_folds, start_frac=0.5):
    return np.linspace(int(len(dates) * start_frac), len(dates), n_folds + 1).astype(int)


def inner_select(d, cols, train_end_date, n_inner):
    """
    只在外層訓練期內做走查，逐檔評分，回傳 (入選清單, 逐檔加權指標)。
    """
    dd = d[d['trade_date'] < train_end_date]
    dates = np.sort(dd['trade_date'].unique())
    bounds = fold_bounds(dates, n_inner)
    per = []
    for i in range(n_inner):
        lo, hi = dates[bounds[i]], dates[bounds[i + 1] - 1]
        te = (dd['trade_date'] >= lo) & (dd['trade_date'] <= hi)
        tr = dd['trade_date'] < dates[max(bounds[i] - HORIZON, 0)]
        sub = fit_predict(dd, cols, tr, te)
        per.append(per_ticker(sub))
    w = weighted_ticker(per)
    chosen = sorted(set(tk for tk, r in w.items() if passes(r)) | set(REFERENCE))
    return chosen, w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--outer', type=int, default=3)
    ap.add_argument('--inner', type=int, default=2)
    args = ap.parse_args()

    print(f'候選 {len(UNIVERSE)} 檔：{" ".join(UNIVERSE)}')
    d_all, cols = build(UNIVERSE)
    print(f'全候選面板 {len(d_all):,} 列　{d_all.trade_date.min().date()} ~ {d_all.trade_date.max().date()}')

    dates = np.sort(d_all['trade_date'].unique())
    bounds = fold_bounds(dates, args.outer)

    fold_reports = []
    for k in range(args.outer):
        lo, hi = dates[bounds[k]], dates[bounds[k + 1] - 1]
        train_end = dates[max(bounds[k] - HORIZON, 0)]
        print(f'\n外層折 {k + 1}：測試 {str(lo)[:10]} ~ {str(hi)[:10]}')

        # 內層：只看訓練期，逐檔過門檻
        chosen, inner_w = inner_select(d_all, cols, train_end, args.inner)
        print(f'  內層入選 {len(chosen)} 檔：{" ".join(chosen)}')

        # 以入選清單重建面板 → 訓練期重訓 → 外層測試期評分
        def score(tickers):
            d, c = build(tickers)
            te = (d['trade_date'] >= lo) & (d['trade_date'] <= hi)
            tr = d['trade_date'] < train_end
            return fit_predict(d, c, tr, te)

        sub_new = score(chosen)
        sub_cur = score(CURRENT)
        sub_all = score(UNIVERSE)
        shared = sorted(set(CURRENT) & set(chosen))

        rep = {
            'fold': k + 1, 'from': str(lo)[:10], 'to': str(hi)[:10],
            'chosen': chosen, 'inner': inner_w,
            'new_on_shared': overall(sub_new, shared),
            'cur_on_shared': overall(sub_cur, shared),
            'new_all': overall(sub_new, [t for t in chosen if t not in TAUTOLOGICAL]),
            'cur_all': overall(sub_cur),
            'all_all': overall(sub_all, [t for t in UNIVERSE if t not in TAUTOLOGICAL]),
            'new_per_ticker': per_ticker(sub_new),
        }
        fold_reports.append(rep)
        ns, cs = rep['new_on_shared'], rep['cur_on_shared']
        print(f'  原 12 檔中留下的 {len(shared)} 檔：新清單模型相關 {ns["corr"]:.4f} / '
              f'原清單模型 {cs["corr"]:.4f}')

    # ── 穩定性：≥2/3 折入選才留下 ──────────────────────────────────────────
    counts = {}
    for r in fold_reports:
        for tk in r['chosen']:
            counts[tk] = counts.get(tk, 0) + 1
    final = sorted(tk for tk, n in counts.items() if n / args.outer >= STABILITY_MIN)
    added = [t for t in final if t not in CURRENT]
    removed = [t for t in CURRENT if t not in final]

    # 最終清單在各外層折的逐檔成績（以該折入選清單的模型為準，只取最終清單中的檔）
    final_per = weighted_ticker([{tk: r for tk, r in fr['new_per_ticker'].items() if tk in final}
                                 for fr in fold_reports])

    # 判定 1：原 12 檔中留下的列，相關不得退步超過容忍值（各折加權）
    def wavg(key, sel):
        ws = [(fr[sel]['n_test'], fr[sel][key]) for fr in fold_reports if fr[sel]]
        return sum(n * v for n, v in ws) / sum(n for n, _ in ws)
    reg = wavg('corr', 'new_on_shared') - wavg('corr', 'cur_on_shared')
    ok_regression = reg >= -REGRESSION_TOL
    # 判定 2：新增標的各自過門檻
    added_fail = [t for t in added if t not in final_per or not passes(final_per[t])]
    ok_added = not added_fail
    deploy = ok_regression and ok_added and len(final) >= 8

    print(f'\n最終清單 {len(final)} 檔：{" ".join(final)}')
    print(f'  新增：{" ".join(added) or "無"}　退場：{" ".join(removed) or "無"}')
    print(f'  原 12 檔留下者的相關變化 {reg:+.4f}（容忍 −{REGRESSION_TOL}）→ {"通過" if ok_regression else "未通過"}')
    print(f'  新增標的過門檻：{"全部通過" if ok_added else "未通過：" + " ".join(added_fail)}')
    print(f'判定：{"採用新清單" if deploy else "維持原清單"}')

    write_report(fold_reports, final, added, removed, final_per, reg, ok_regression,
                 added_fail, deploy, counts, args)
    return final if deploy else CURRENT


def _fmt(r):
    if not r:
        return '– | – | – | –'
    return (f"{r['n_test']:,} | {r['corr']:.4f} | {r['dir_acc']*100:.2f}% | "
            f"{r['dir_base']*100:.2f}%")


def write_report(folds, final, added, removed, final_per, reg, ok_regression,
                 added_fail, deploy, counts, args):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'us_universe.md')
    L = [
        '# 美股標的清單重新檢討（Iteration 34）', '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**候選：** 現行 {len(CURRENT)} 檔 + {len(CANDIDATES)} 檔 ＝ {len(UNIVERSE)} 檔',
        f'**驗證：** 巢狀走查（外 {args.outer} 折評分 / 內 {args.inner} 折挑選）；'
        f'逐檔門檻：相關 ≥{DEPLOY_MIN_CORR}、方向贏多數類別 {DEPLOY_DIR_MARGIN*100:.0f}pp',
        f'**穩定性：** 須在 ≥{STABILITY_MIN:.0%} 的外層折入選',
        f'**固定保留：** {" ".join(REFERENCE)}（大盤特徵的來源，不參與退場）', '',
        '## 結論', '',
        f'**{"採用新清單" if deploy else "維持原清單"}**：最終 {len(final)} 檔　'
        f'新增 {" ".join(added) or "無"}　退場 {" ".join(removed) or "無"}', '',
        f'- 原 12 檔中留下者，新清單模型 vs 原清單模型的外層相關差 {reg:+.4f}'
        f'（容忍 −{REGRESSION_TOL}）→ {"通過" if ok_regression else "未通過"}',
        f'- 新增標的各自過門檻：{"全部通過" if not added_fail else "未通過 " + " ".join(added_fail)}',
        '', '## 各折入選（穩定性）', '',
        '| 標的 | 入選折數 | ' + ' | '.join(f'折 {f["fold"]}' for f in folds) + ' |',
        '|------|---------|' + '|'.join('------' for _ in folds) + '|',
    ]
    for tk in UNIVERSE:
        marks = ['✓' if tk in f['chosen'] else '·' for f in folds]
        tag = '' if tk in CURRENT else '（候選）'
        L.append(f'| {tk}{tag} | {counts.get(tk, 0)}/{len(folds)} | ' + ' | '.join(marks) + ' |')

    L += ['', '## 外層評分（測試期完全沒被挑選看過）', '',
          '「原 12 檔留下者」是判定 1 的依據：清單變了橫斷面特徵就變，要確認沒拖累原本準的標的。',
          '「新清單整體」不含 EWT——它本身就是台股，不拿它撐平均。', '',
          '| 折 | 測試期 | 對象 | 測試列 | 相關 | 方向 | 多數類別 |',
          '|----|--------|------|-------|------|------|---------|']
    for f in folds:
        L.append(f"| {f['fold']} | {f['from']} ~ {f['to']} | 原清單模型／原 12 檔留下者 | {_fmt(f['cur_on_shared'])} |")
        L.append(f"| {f['fold']} | | 新清單模型／原 12 檔留下者 | {_fmt(f['new_on_shared'])} |")
        L.append(f"| {f['fold']} | | 原清單模型／原 12 檔全部 | {_fmt(f['cur_all'])} |")
        L.append(f"| {f['fold']} | | 新清單模型／新清單整體 | {_fmt(f['new_all'])} |")
        L.append(f"| {f['fold']} | | 全候選模型／全候選整體 | {_fmt(f['all_all'])} |")

    L += ['', '## 最終清單逐檔（外層測試期加權）', '',
          '| 標的 | 狀態 | 測試列 | 相關 | 方向 | 多數類別 | 贏幅 | 門檻 |',
          '|------|------|-------|------|------|---------|------|------|']
    for tk, r in sorted(final_per.items(), key=lambda kv: -kv[1]['corr']):
        st = '新增' if tk in added else '留任'
        if tk in TAUTOLOGICAL:
            st += '（本身是台股）'
        L.append(f"| {tk} | {st} | {r['n_test']:,} | {r['corr']:.3f} | {r['dir_acc']*100:.2f}% | "
                 f"{r['dir_base']*100:.2f}% | {r['margin']*100:+.2f}pp | {'✓' if passes(r) else '✗'} |")

    L += ['', '## 退場標的在內層的成績（各折）', '',
          '| 標的 | 折 | 相關 | 方向 | 多數類別 | 贏幅 |',
          '|------|----|------|------|---------|------|']
    for tk in removed + [t for t in CANDIDATES if t not in final]:
        for f in folds:
            r = f['inner'].get(tk)
            if r:
                L.append(f"| {tk}{'' if tk in CURRENT else '（候選）'} | {f['fold']} | {r['corr']:.3f} | "
                         f"{r['dir_acc']*100:.2f}% | {r['dir_base']*100:.2f}% | {r['margin']*100:+.2f}pp |")
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(L))
    print(f'報告已寫入 {path}')


if __name__ == '__main__':
    main()
