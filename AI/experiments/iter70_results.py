"""
Iteration 70 結果檔產生器：文獻第二批第五代（#86 `win3+mom+ovn1m`、#87 `win3+mom+illiq`、#88 valid）對候選 #30／#38，
加 `illiq` 的診斷：它和 60 日成交金額、`mom` 的橫斷面相關，以及兩個組合持股的流動性名次（往小型股偏了多少）。
用法（在 Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter70_results.py
結果檔是證據，不手改。來源：portfolio_runs.metrics；portfolio_signal.eligible／signal_*／scores_on。
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
from db.connection import get_conn  # noqa: E402
import portfolio_signal as ps  # noqa: E402
from portfolio_backtest import SEGMENTS  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'UnifiedModel', 'results', 'portfolio_iter70_illiq.md')
NEW = [86, 87, 88]
BASE = [30, 38, 53, 62]
COLS = [('ann_active', '年化主動', '{:+.2%}'), ('info_ratio', 'IR', '{}'), ('dsr', 'DSR', '{:.3f}'), ('tracking_error', '追蹤誤差', '{:.1%}'),
        ('rel_mdd', '相對最大落後', '{:.1%}'), ('monthly_win_rate', '月勝率', '{:.0%}'), ('turnover_annual', '換手', '{}'),
        ('cost_drag_annual', '成本/年', '{:.2%}'), ('cagr_port', '組合 CAGR', '{:.1%}'), ('cagr_bench', '0050 CAGR', '{:.1%}')]


def metrics_table(conn) -> list:
    cur = conn.cursor()
    cur.execute("SELECT experiment_n, name, segment, metrics, n_rebalances, notes, tag FROM portfolio_runs WHERE experiment_n = ANY(%s) ORDER BY experiment_n",
                (NEW + BASE,))
    rows = cur.fetchall()
    L = [f'## 一、新實驗（N {min(NEW)}～{max(n for n, *_ in rows)}）與對照列（`portfolio_runs.metrics`）', '',
         '| N | 設定 | 段 | ' + ' | '.join(c[1] for c in COLS) + ' | 調倉次數 | 備註 |',
         '|---|---|---|' + '---|' * len(COLS) + '---|---|']
    for n, name, seg, m, nreb, notes, tag in rows:
        cells = ['' if m.get(k) is None else fmt.format(m.get(k)) for k, _, fmt in COLS]
        mark = ('對照' if n in BASE else '新') + (f'，tag={tag}' if tag else '')
        L.append(f"| {n} | {name} | {seg} | " + ' | '.join(cells) + f" | {nreb} | {mark} |")
    L += ['', 'DSR 欄是各列跑當時的累積 N 算的，對照列偏高，**不可橫向比**；年化主動、IR、追蹤誤差可以。#53／#62 是 Iteration 53 的 `rev_accel+mom`，候選以外另一個跨段過門檻的家族，放進來比。', '']
    years = sorted({y for *_, m, _, _, _ in rows for y in (m.get('yearly_active') or {})})
    L += ['## 二、逐年主動報酬（`metrics.yearly_active`）', '', '| N | 設定 | ' + ' | '.join(years) + ' |', '|---|---|' + '---|' * len(years)]
    for n, name, seg, m, *_ in rows:
        ya = m.get('yearly_active') or {}
        L.append(f"| {n} | {name} | " + ' | '.join(f"{ya[y]:+.1%}" if ya.get(y) is not None else '' for y in years) + ' |')
    return L


SECTION = {'dev': '三', 'valid': '四'}


def illiq_diagnostics(segment: str) -> list:
    """每個訊號日：ρ(illiq, 60 日成交金額)、ρ(illiq, mom)；`win3+mom` 與 `win3+mom+illiq` 前 20 名的流動性名次中位數（1 = 池內最大）與重疊數。"""
    s, e = SEGMENTS[segment]
    mkt = ps.Market(ps.load_prices(s, e), ps.load_universe_meta())
    sur = ps.surprises(ps.load_revenue(s))
    rows = []
    for sd, _ in ps.rebalance_schedule(mkt, s, e):
        ids = ps.eligible(mkt, sd)
        base = ps.scores_on('win3+mom', mkt, sur, sd, ids)
        if len(base) < 30:
            continue
        il = ps.signal_illiq(mkt, sd).reindex(ids)
        liq_rank = mkt.liq.loc[sd, ids].rank(ascending=False)
        mom = ps.signal_mom(mkt, sd).reindex(ids)
        new = ps.scores_on('win3+mom+illiq', mkt, sur, sd, ids)
        top_b = base.sort_values(ascending=False).index[:20]
        top_n = new.sort_values(ascending=False).index[:20]
        rows.append({'signal_day': sd.date(), 'rho_liq': float(il.rank().corr(liq_rank)), 'rho_mom': float(il.rank().corr(mom.rank())),
                     'liqrank_base': float(liq_rank.reindex(top_b).median()), 'liqrank_new': float(liq_rank.reindex(top_n).median()),
                     'overlap': len(set(top_b) & set(top_n)), 'n_illiq': int(il.notna().sum()), 'n_pool': len(ids)})
    df = pd.DataFrame(rows).set_index('signal_day')
    L = [f'## {SECTION[segment]}、`illiq` 的診斷（{segment}，{len(df)} 個有分數的訊號日，候選池內）', '',
         '| 統計 | ρ(illiq, 流動性名次) | ρ(illiq, mom) | 前 20 流動性名次中位數 win3+mom | 前 20 流動性名次中位數 win3+mom+illiq | 前 20 重疊 | 池內有 illiq | 股票池 |',
         '|---|---|---|---|---|---|---|---|']
    for name, fn in (('最小', 'min'), ('中位數', 'median'), ('最大', 'max')):
        v = getattr(df, fn)()
        L.append(f"| {name} | {v['rho_liq']:.2f} | {v['rho_mom']:.2f} | {v['liqrank_base']:.0f} | {v['liqrank_new']:.0f} | {v['overlap']:.0f} | {v['n_illiq']:.0f} | {v['n_pool']:.0f} |")
    L += ['', '流動性名次：訊號日 60 日平均成交金額在股票池內的名次，1 = 最大；ρ(illiq, 流動性名次) 為正表示 `illiq` 高的就是池內成交金額小的。ρ 是 Spearman。']
    if segment == 'valid':
        L.append('這一節是對已跑過的 #88 的持股組成描述，**描述性、不得用來設計下一條假設**（驗證期只看一次）。')
    L.append('')
    return L


def holdings_liq_rank(conn) -> list:
    """#30／#38／#87／#88 實際成交持股（portfolio_positions.filled）在調倉日的**全市場**流動性名次分佈——
    回測的滑價是用這個名次判的（> 200 用 0.30%，其餘 0.15%，portfolio_backtest.COSTS）。"""
    cur = conn.cursor()
    cur.execute("SELECT r.experiment_n, r.segment, p.rebalance_date, p.stock_id FROM portfolio_positions p JOIN portfolio_runs r ON r.id = p.run_id "
                "WHERE r.experiment_n = ANY(%s) AND p.filled AND p.stock_id <> %s ORDER BY 1, 3", ([30, 38, 87, 88], ps.TSMC))
    pos = pd.DataFrame(cur.fetchall(), columns=['n', 'segment', 'rebalance_date', 'stock_id'])
    pos['rebalance_date'] = pd.to_datetime(pos['rebalance_date'])
    out = []
    for seg in ('dev', 'valid'):
        s, e = SEGMENTS[seg]
        mkt = ps.Market(ps.load_prices(s, e), ps.load_universe_meta())
        sub = pos[pos['segment'] == seg]
        for n, g in sub.groupby('n'):
            ranks = []
            for d, gg in g.groupby('rebalance_date'):
                lr = mkt.liq.loc[d].rank(ascending=False)
                ranks.extend(lr.reindex(gg['stock_id']).dropna().tolist())
            r = pd.Series(ranks)
            out.append((n, seg, len(r), r.median(), r.quantile(0.9), r.max(), (r > 150).mean(), (r > 200).mean()))
    L = ['## 五、實際持股的全市場流動性名次（`portfolio_positions.filled`，不含台積電；名次 1 = 全市場 60 日成交金額最大）', '',
         '| N | 段 | 持股筆數 | 名次中位數 | 90 分位 | 最大 | 名次 > 150 的比例 | 名次 > 200（滑價 0.30%）的比例 |', '|---|---|---|---|---|---|---|---|']
    for n, seg, cnt, med, q90, mx, p150, p200 in out:
        L.append(f'| {n} | {seg} | {cnt} | {med:.0f} | {q90:.0f} | {mx:.0f} | {p150:.0%} | {p200:.0%} |')
    L += ['', '回測對名次 ≤ 200 的股票一律滑價 0.15%、> 200 才 0.30%；這張表說明 #87／#88 有多少持股落在 150～200（付和候選一樣的滑價、但成交金額較小）與 > 200。', '']
    return L


def size_tilt_by_year() -> list:
    """每年「池內流動性名次 101～300 等權」減「名次 1～100 等權」的報酬（訊號日收盤到下一個訊號日收盤，每月換池）——
    描述池內小型股相對大型股的年度表現，不是回測、不算 N。"""
    rows = []
    for seg in ('dev', 'valid'):
        s, e = SEGMENTS[seg]
        mkt = ps.Market(ps.load_prices(s, e), ps.load_universe_meta())
        sched = [sd for sd, _ in ps.rebalance_schedule(mkt, s, e)]
        for a, b in zip(sched[:-1], sched[1:]):
            ids = ps.eligible(mkt, a)
            if len(ids) < 200:
                continue
            liq_rank = mkt.liq.loc[a, ids].rank(ascending=False)
            ret = mkt.adj.loc[b, ids] / mkt.adj.loc[a, ids] - 1
            big, small = ret[liq_rank <= 100].mean(), ret[liq_rank > 100].mean()
            bench = mkt.adj.at[b, ps.BENCH] / mkt.adj.at[a, ps.BENCH] - 1
            rows.append({'year': a.year, 'big': big, 'small': small, 'bench': bench})
    df = pd.DataFrame(rows)
    L = ['## 六、池內大型股對小型股的年度報酬（訊號日到下一個訊號日、每月換池、等權、不含成本；描述性，不是回測）', '',
         '| 年 | 月數 | 名次 1～100 等權（累積） | 名次 101～300 等權（累積） | 0050（累積） | 小減大 |', '|---|---|---|---|---|---|']
    for y, g in df.groupby('year'):
        cb, cs, c0 = (1 + g['big']).prod() - 1, (1 + g['small']).prod() - 1, (1 + g['bench']).prod() - 1
        L.append(f'| {y} | {len(g)} | {cb:+.1%} | {cs:+.1%} | {c0:+.1%} | {cs - cb:+.1%} |')
    L += ['', '2018 年只有動能歷史足夠之後的月份；每年的月數見第二欄。', '']
    return L


def main():
    with get_conn() as conn:
        L = ['# Iteration 70 結果：文獻第二批第五代——隔夜短期持續、Amihud 非流動性', '',
             '產生：`AI/experiments/iter70_results.py`（2026-10-15）。事前登記：`AI/experiments/iter70_hypothesis.md`。網格：`iter70_grid.json`，日誌 `iter70_dev.log`、`iter70_valid.log`。', '']
        L += metrics_table(conn)
        hold = holdings_liq_rank(conn)
    L += illiq_diagnostics('dev')
    L += illiq_diagnostics('valid')
    L += hold
    L += size_tilt_by_year()
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')
    print('寫入', OUT)


if __name__ == '__main__':
    main()
