"""
Iteration 67 結果檔產生器：三年期市場狀態閘門（#81）對候選 #30，以及三年期／一年期閘門在開發期與驗證期每個訊號日的狀態。
用法（在 Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter67_results.py
結果檔是證據，不手改。來源：portfolio_runs.metrics；portfolio_signal.market_state_up（0050 長歷史 load_bench_history）。
"""
import os
import sys
from datetime import date

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db.connection import get_conn  # noqa: E402
import portfolio_signal as ps  # noqa: E402
from portfolio_backtest import SEGMENTS  # noqa: E402
import iter66_results as r66  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'UnifiedModel', 'results', 'portfolio_iter67_gate3y.md')


def gate_states() -> list:
    L = ['## 二、閘門狀態：每個調倉訊號日的 0050 一年（252 日）與三年（756 日）報酬是否 < 0（`market_state_up`，0050 長歷史 `load_bench_history`）', '']
    meta = ps.load_universe_meta()
    for seg in ('dev', 'valid'):
        s, e = SEGMENTS[seg]
        mkt = ps.Market(ps.load_prices(s, e), meta)
        mkt.bench_hist = ps.load_bench_history(s)
        rows = []
        for sd, _ in ps.rebalance_schedule(mkt, s, e):
            h = mkt.bench_hist[mkt.bench_hist.index <= sd]
            r1 = h.iloc[-1] / h.iloc[-1 - 252] - 1 if len(h) > 252 else None
            r3 = h.iloc[-1] / h.iloc[-1 - 756] - 1 if len(h) > 756 else None
            rows.append((sd.date(), r1, r3, ps.market_state_up(mkt, sd, 252), ps.market_state_up(mkt, sd, 756)))
        down1 = [str(d) for d, _, _, u1, _ in rows if u1 is False]
        down3 = [str(d) for d, _, _, _, u3 in rows if u3 is False]
        none3 = sum(1 for r in rows if r[4] is None)
        min3 = min(rows, key=lambda x: x[2] if x[2] is not None else 9)
        L.append(f'- {seg}：{len(rows)} 個訊號日；一年期 DOWN {len(down1)} 個（{"、".join(down1) or "無"}）；'
                 f'三年期 DOWN {len(down3)} 個（{"、".join(down3) or "無"}）、歷史不足 {none3} 個；三年期報酬最低的訊號日 {min3[0]}：{min3[2]:+.1%}')
    return L


def daily_min_3y() -> list:
    """0050 每個交易日往回看三年（756 日）報酬的最低值（不只訊號日）。"""
    hist = ps.load_bench_history(SEGMENTS['dev'][0])
    r3 = (hist / hist.shift(756) - 1).loc['2018-01-02':'2024-09-30'].dropna()
    r1 = (hist / hist.shift(252) - 1).loc['2018-01-02':'2024-09-30'].dropna()
    return ['## 三、0050 逐日往回看的報酬（2018-01-02～2024-09-30 每個交易日，`load_bench_history`）', '',
            f'- 三年（756 日）：{len(r3)} 個交易日，最低 {r3.min():+.1%}（{r3.idxmin():%Y-%m-%d}），< 0 的天數 {(r3 < 0).sum()}',
            f'- 一年（252 日）：{len(r1)} 個交易日，最低 {r1.min():+.1%}（{r1.idxmin():%Y-%m-%d}），< 0 的天數 {(r1 < 0).sum()}']


def tsmc_fallback_check() -> list:
    """不暖機 vs 暖機 420 天：estimate_tsmc_weight 第一次回非 None 的日期（證明 bench_hist 不會改變 fallback 期、warmup 也不會）。"""
    from datetime import timedelta
    meta = ps.load_universe_meta()
    out = ['## 四、`estimate_tsmc_weight` 第一次估得出的日期（不暖機 vs 暖機 420 天；全市場日線從 2018-01-02 起）', '']
    for label, load_start in (('不暖機（候選 #30 與 #81 的載法）', SEGMENTS['dev'][0]), ('暖機 420 天', SEGMENTS['dev'][0] - timedelta(days=420))):
        mkt = ps.Market(ps.load_prices(load_start, date(2018, 12, 31)), meta)
        days = [pd.Timestamp(x) for x in mkt.days if pd.Timestamp(x) >= pd.Timestamp('2018-01-01')]
        first = next((d for d in days if ps.estimate_tsmc_weight(mkt, d) is not None), None)
        full = mkt.adj.index[mkt.adj.index >= '2018-01-01']
        n_before = int((mkt.adj.index < pd.Timestamp('2018-01-01')).sum())
        out.append(f"- {label}：2018 年前只有 0050 的列數 {n_before}；第一次估得出 {first.date() if first is not None else None}（全市場第 {int((full <= first).sum()) if first is not None else None} 個交易日）")
    return out


def main():
    r66.NEW, r66.BASE = [81], [30, 38, 75]
    with get_conn() as conn:
        L = ['# 第二代：三年期市場狀態閘門（Iteration 67）', '',
             f'**產生：** {date.today()}（`AI/experiments/iter67_results.py`）', '',
             '事前登記 `AI/experiments/iter67_hypothesis.md`；讀法見 `AI/Doc/Iterations/Iteration-67.md`。', '']
        L += r66.metrics_table(conn) + ['']
        L += gate_states() + ['']
        L += daily_min_3y() + ['']
        L += tsmc_fallback_check()
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')
    print('寫入', os.path.abspath(OUT))


if __name__ == '__main__':
    main()
