"""Iteration 84：資料更新後（Iteration 83：事件表改交易所檔、全市場 adj_close 三檔重算、0050 重建），把已登記的 run 用日誌裡的參數原樣重算，
與日誌指標、持股並排。不寫 portfolio_runs（與 `--attach-series` 同一條路；N 不動），不開保留期。事前登記：AI/experiments/iter84_hypothesis.md。
用法（Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter84_recompute.py [run_id ...]  → UnifiedModel/results/portfolio_iter84_data_refresh.md"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
import portfolio_backtest as pb  # noqa: E402
from db.connection import get_conn  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
OUT = os.path.join(ROOT, 'UnifiedModel', 'results', 'portfolio_iter84_data_refresh.md')
RUNS = [int(a) for a in sys.argv[1:]] or [30, 38, 44, 87, 88, 90, 92, 94, 96, 106, 108, 54, 58, 62]
KEYS = ['ann_active', 'info_ratio', 'tracking_error', 'rel_mdd', 'cagr_port', 'cagr_bench', 'turnover_annual', 'n_rebalances']


def logged(rid):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT name, signal, segment, period_start, period_end, params, metrics, tag FROM portfolio_runs WHERE id = %s", (rid,))
        row = cur.fetchone()
        cur.execute("SELECT rebalance_date, stock_id FROM portfolio_positions WHERE run_id = %s", (rid,))
        pos = set(cur.fetchall())
        cur.execute("SELECT max(experiment_n), count(*) FROM portfolio_runs")
        n = cur.fetchone()
    return row, pos, n


def fmt(k, v):
    if v is None:
        return '—'
    if k in ('ann_active', 'tracking_error', 'rel_mdd', 'cagr_port', 'cagr_bench'):
        return f'{float(v) * 100:+.2f}%'
    return f'{v}'


def main():
    t0 = datetime.now()
    cache = {}
    lines = ['# Iteration 84：資料更新後已登記 run 的原樣重算（不寫 portfolio_runs）', '',
             f'**產生：** {t0:%Y-%m-%d %H:%M}　**腳本：** `AI/experiments/iter84_recompute.py`　**事前登記：** `AI/experiments/iter84_hypothesis.md`', '',
             '每列用 `portfolio_runs.params` 原樣重算（`portfolio_backtest.run(save=False)`），與日誌 `metrics` 與 `portfolio_positions` 比。「持股差」＝（訊號日, 股票）對稱差的筆數／日誌筆數。',
             'DSR 不列：重算時的 N 是下一號、與日誌不可比。', '',
             '| run | 名稱 | 段 | 指標 | 日誌 | 重算 | 差 |', '|---|---|---|---|---|---|---|']
    summary = []
    n_before = logged(RUNS[0])[2]          # 重算前的 N，迴圈外取一次
    for rid in RUNS:
        (name, signal, seg, ps_, pe, params, met, tag), pos_old, _ = logged(rid)
        res = pb.run(signal, seg, ps_, pe, params.get('top_n', 20), params.get('buffer', 40), params.get('universe_n', 300),
                     params.get('excl_limit_pct', 0.10), params.get('tsmc_weight'), params.get('costs', pb.COSTS), save=False,
                     tranches=params.get('tranches', 1), weighting=params.get('weighting', 'equal'), _cache=cache,
                     warmup_days=params.get('warmup_days', 0))
        m = res['metrics']
        p = res['positions']
        pos_new = set(zip([d.date() if hasattr(d, 'date') else d for d in p['rebalance_date']], p['stock_id'])) if len(p) else set()
        sym = pos_old ^ pos_new
        first = True
        for k in KEYS:
            a, b = met.get(k), m.get(k)
            d = '' if a is None or b is None else (f'{(float(b) - float(a)) * 100:+.2f} pp' if k in ('ann_active', 'tracking_error', 'rel_mdd', 'cagr_port', 'cagr_bench') else f'{float(b) - float(a):+g}')
            same = (a is not None and b is not None and abs(float(b) - float(a)) < 1e-9)
            lines.append(f"| {'#' + str(rid) if first else ''} | {name if first else ''} | {seg if first else ''} | {k} | {fmt(k, a)} | {fmt(k, b)} | {'相同' if same else d} |")
            first = False
        lines.append(f"| | | | 持股差 | {len(pos_old)} 筆 | {len(pos_new)} 筆 | {len(sym)} 筆{'（相同）' if not sym else ''} |")
        da = (float(m['ann_active']) - float(met['ann_active'])) * 100
        summary.append((rid, name, seg, tag, da, len(sym), len(pos_old), float(met['ann_active']) * 100, float(m['ann_active']) * 100,
                        float(met['cagr_bench']) == float(m['cagr_bench'])))
        print(f'#{rid} {name}: ann_active 日誌 {float(met["ann_active"]) * 100:+.2f}% 重算 {float(m["ann_active"]) * 100:+.2f}%（{da:+.2f} pp）、持股差 {len(sym)}/{len(pos_old)}、基準同 {float(met["cagr_bench"]) == float(m["cagr_bench"])}', flush=True)
        if sym:
            diff_old = sorted(pos_old - pos_new)
            diff_new = sorted(pos_new - pos_old)
            lines.append(f"| | | | 只在日誌 | {len(diff_old)} 筆 | | {', '.join(f'{d} {s}' for d, s in diff_old[:12])}{' …' if len(diff_old) > 12 else ''} |")
            lines.append(f"| | | | 只在重算 | | {len(diff_new)} 筆 | {', '.join(f'{d} {s}' for d, s in diff_new[:12])}{' …' if len(diff_new) > 12 else ''} |")
    n_after = logged(RUNS[0])[2]
    lines += ['', '## 摘要', '', '| run | 名稱 | 段 | tag | 年化主動 日誌 → 重算 | 差 | 持股差 | 基準相同 |', '|---|---|---|---|---|---|---|---|']
    for rid, name, seg, tag, da, ns, npos, a, b, bs in summary:
        lines.append(f'| #{rid} | {name} | {seg} | {tag or ""} | {a:+.2f}% → {b:+.2f}% | {da:+.2f} pp | {ns}/{npos} | {"是" if bs else "**否**"} |')
    lines += ['', f'portfolio_runs：重算前 N {n_before[0]}／{n_before[1]} 列，重算後 N {n_after[0]}／{n_after[1]} 列（沒有新增）。',
              f'耗時 {(datetime.now() - t0).total_seconds() / 60:.1f} 分。保留期未開。']
    with open(OUT, 'w', encoding='utf-8', newline='') as f:
        f.write('\n'.join(lines) + '\n')
    print('寫入', OUT)


if __name__ == '__main__':
    main()
