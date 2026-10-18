"""
Iteration 85 結果檔產生器：第十一代（#109 `nsblf`、#110 `win3+mom+nsblf`、#111 `indlead`、#112 `win3+mom+indlead`，valid #113／#114）對候選 #30／#38、`mom` 單獨 #70、
第十代的 #106／#108，加登記裡列的診斷：開發期每個訊號日池內有值的股票數、ρ(nsblf, nsir)、ρ(nsblf, mom)、ρ(indlead, mom)、ρ(indlead, indmom)（Spearman）、
相加訊號前 20 與候選 `win3+mom` 前 20 的重疊、實際持股與 #30／#38 的交集（portfolio_positions）。
用法（Crawler 目錄）：PYTHONUTF8=1 PYTHONWARNINGS=ignore python ../AI/experiments/iter85_results.py
結果檔是證據，不手改。來源：portfolio_runs.metrics、portfolio_positions、market_margin_daily、market_foreign_holding_daily、market_universe；portfolio_signal.*。
"""
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
from db.connection import get_conn  # noqa: E402
import portfolio_signal as ps  # noqa: E402
from portfolio_backtest import SEGMENTS  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'UnifiedModel', 'results', 'portfolio_iter85_shortflow_indlead.md')
NAMES = ['nsblf-t3-tsmcest-dev', 'win3+mom+nsblf-t3-tsmcest-dev', 'indlead-t3-tsmcest-dev', 'win3+mom+indlead-t3-tsmcest-dev',
         'win3+mom+nsblf-t3-tsmcest-valid', 'win3+mom+indlead-t3-tsmcest-valid']
BASE = [30, 70, 106, 38, 108]
COLS = [('ann_active', '年化主動', '{:+.2%}'), ('info_ratio', 'IR', '{}'), ('dsr', 'DSR', '{:.3f}'), ('tracking_error', '追蹤誤差', '{:.1%}'),
        ('rel_mdd', '相對最大落後', '{:.1%}'), ('monthly_win_rate', '月勝率', '{:.0%}'), ('turnover_annual', '換手', '{}'),
        ('cost_drag_annual', '成本/年', '{:.2%}'), ('cagr_port', '組合 CAGR', '{:.1%}'), ('cagr_bench', '0050 CAGR', '{:.1%}')]


def runs(conn):
    cur = conn.cursor()
    cur.execute("SELECT id, experiment_n, name, segment, metrics, n_rebalances, notes, tag FROM portfolio_runs WHERE name = ANY(%s) OR experiment_n = ANY(%s) ORDER BY experiment_n",
                (NAMES, BASE))
    return cur.fetchall()


def section_metrics(rows):
    new = [r for r in rows if r[2] in NAMES]
    L = [f'## 一、新實驗（N {min(r[1] for r in new)}～{max(r[1] for r in new)}）與對照列（`portfolio_runs.metrics`）', '',
         '| N | 設定 | 段 | ' + ' | '.join(c[1] for c in COLS) + ' | 調倉次數 | 備註 |', '|---|---|---|' + '---|' * len(COLS) + '---|---|']
    for _, n, name, seg, m, nreb, notes, tag in rows:
        cells = ['' if m.get(k) is None else fmt.format(m.get(k)) for k, _, fmt in COLS]
        mark = ('新' if name in NAMES else '對照') + (f'，tag={tag}' if tag else '')
        L.append(f"| {n} | {name} | {seg} | " + ' | '.join(cells) + f" | {nreb} | {mark} |")
    L += ['', 'DSR 欄是各列跑當時的累積 N 算的，**不可橫向比**；年化主動、IR、追蹤誤差可以。#70 是 `mom` 單獨（Iteration 66）；#106／#108 是第十代的放空餘額相加（dev／valid）；#38 是候選的驗證期。', '']
    years = sorted({y for *_, m, _, _, _ in rows for y in (m.get('yearly_active') or {})})
    L += ['## 二、逐年主動報酬（`metrics.yearly_active`）', '', '| N | 設定 | ' + ' | '.join(years) + ' |', '|---|---|' + '---|' * len(years)]
    for _, n, name, seg, m, *_ in rows:
        ya = m.get('yearly_active') or {}
        L.append(f"| {n} | {name} | " + ' | '.join(f"{ya[y]:+.1%}" if ya.get(y) is not None else '' for y in years) + ' |')
    L.append('')
    return L


def section_diag():
    start, end = SEGMENTS['dev']
    prices = ps.load_prices(start, end)
    mkt = ps.Market(prices, ps.load_universe_meta())
    mkt.margin = ps.load_margin(start, end)
    mkt.holding = ps.load_holding(start, end)
    sur = ps.surprises(ps.load_revenue(start))
    sched = ps.rebalance_schedule(mkt, start, end)
    rows = []
    for d, _ in sched:
        ids = ps.eligible(mkt, d)
        sig = {k: fn(mkt, d).reindex(ids) for k, fn in (('nsblf', ps.signal_nsblf), ('nsir', ps.signal_nsir), ('mom', ps.signal_mom),
                                                        ('indlead', ps.signal_indlead), ('indmom', ps.signal_indmom))}
        df = pd.DataFrame(sig)
        base = ps.scores_on('win3+mom', mkt, sur, d, ids)
        top_base = set(base.nlargest(20).index) if len(base) else set()
        ov = {}
        for s in ('win3+mom+nsblf', 'win3+mom+indlead'):
            sc = ps.scores_on(s, mkt, sur, d, ids)
            ov[s] = len(set(sc.nlargest(20).index) & top_base) if len(sc) else np.nan
        rows.append({'d': d.date(), 'pool': len(ids), 'n_nsblf': int(df['nsblf'].count()), 'n_nsir': int(df['nsir'].count()),
                     'n_indlead': int(df['indlead'].count()), 'n_mom': int(df['mom'].count()),
                     'sblf_zero': float((df['nsblf'].dropna() == 0).mean()) if df['nsblf'].count() else np.nan,   # 分母只算有值的（審查建議）
                     'r_nsblf_nsir': df['nsblf'].corr(df['nsir'], method='spearman'), 'r_nsblf_mom': df['nsblf'].corr(df['mom'], method='spearman'),
                     'r_indlead_mom': df['indlead'].corr(df['mom'], method='spearman'), 'r_indlead_indmom': df['indlead'].corr(df['indmom'], method='spearman'),
                     'ov_nsblf': ov['win3+mom+nsblf'], 'ov_indlead': ov['win3+mom+indlead']})
    t = pd.DataFrame(rows)
    L = ['## 三、開發期每個訊號日：池內有值股票數、等級相關、前 20 重疊（`portfolio_signal`，只讀）', '',
         f'{len(t)} 個訊號日（{t["d"].iloc[0]}～{t["d"].iloc[-1]}）；池 ＝ `eligible`（流動性前 300、排除漲停前 10%）。', '',
         '| 項目 | 最小 | 中位 | 最大 |', '|---|---|---|---|']
    for k, label in (('pool', '池內股票數'), ('n_mom', '`mom` 有值'), ('n_nsblf', '`nsblf` 有值'), ('n_nsir', '`nsir` 有值'), ('n_indlead', '`indlead` 有值')):
        L.append(f'| {label} | {t[k].min():.0f} | {t[k].median():.0f} | {t[k].max():.0f} |')
    L.append(f'| `sblf` ＝ 0 的比例 | {t["sblf_zero"].min():.1%} | {t["sblf_zero"].median():.1%} | {t["sblf_zero"].max():.1%} |')
    for k, label in (('r_nsblf_nsir', 'ρ(nsblf, nsir)'), ('r_nsblf_mom', 'ρ(nsblf, mom)'), ('r_indlead_mom', 'ρ(indlead, mom)'), ('r_indlead_indmom', 'ρ(indlead, indmom)')):
        L.append(f'| {label}（Spearman） | {t[k].min():+.2f} | {t[k].median():+.2f} | {t[k].max():+.2f} |')
    for k, label in (('ov_nsblf', '`win3+mom+nsblf` 前 20 與 `win3+mom` 前 20 重疊'), ('ov_indlead', '`win3+mom+indlead` 前 20 與 `win3+mom` 前 20 重疊')):
        L.append(f'| {label} | {t[k].min():.0f} | {t[k].median():.0f} | {t[k].max():.0f} |')
    L += ['', '登記的判讀門檻：ρ(nsblf, nsir) > 0.8 → 流量只是餘額的再抽樣；ρ(indlead, indmom) > 0.8 → 同家族。', '']
    return L


def section_positions(conn, rows):
    byname = {r[2]: r[0] for r in rows}
    byn = {r[1]: r[0] for r in rows}
    cur = conn.cursor()
    L = ['## 四、實際持股（`portfolio_positions`）：與候選同段的交集、流動性名次', '', '| run | 對照 | 調倉次數 | 每次交集中位（／20） | 交集最小～最大 | 持股流動性名次中位 |', '|---|---|---|---|---|---|']
    pairs = [('win3+mom+nsblf-t3-tsmcest-dev', 30), ('win3+mom+indlead-t3-tsmcest-dev', 30), ('win3+mom+nsblf-t3-tsmcest-valid', 38), ('win3+mom+indlead-t3-tsmcest-valid', 38),
             ('nsblf-t3-tsmcest-dev', 30), ('indlead-t3-tsmcest-dev', 30)]
    for name, base_n in pairs:
        rid, bid = byname.get(name), byn.get(base_n)
        if not rid or not bid:
            continue
        cur.execute("SELECT rebalance_date, stock_id, rank FROM portfolio_positions WHERE run_id = %s", (rid,))
        a = pd.DataFrame(cur.fetchall(), columns=['d', 'sid', 'rank'])
        cur.execute("SELECT rebalance_date, stock_id FROM portfolio_positions WHERE run_id = %s", (bid,))
        b = pd.DataFrame(cur.fetchall(), columns=['d', 'sid'])
        inter = []
        for d, g in a.groupby('d'):
            bb = set(b[b['d'] == d]['sid'])
            if bb:
                inter.append(len(set(g['sid']) & bb))
        cur.execute("""SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY rk) FROM (
                         SELECT p.stock_id, p.rebalance_date, (SELECT count(*) + 1 FROM market_daily_prices q WHERE q.trade_date = p.rebalance_date AND q.turnover_value > m.turnover_value) AS rk
                         FROM portfolio_positions p JOIN market_daily_prices m ON m.stock_id = p.stock_id AND m.trade_date = p.rebalance_date WHERE p.run_id = %s) s""", (rid,))
        liq = cur.fetchone()[0]
        L.append(f'| {name} | #{base_n} | {a["d"].nunique()} | {np.median(inter) if inter else float("nan"):.0f} | {min(inter) if inter else ""}～{max(inter) if inter else ""} | {liq:.0f} |')
    L.append('')
    return L


def main():
    with get_conn() as conn:
        rows = runs(conn)
        cur = conn.cursor()
        cur.execute("SELECT max(experiment_n), count(*) FROM portfolio_runs")
        n, cnt = cur.fetchone()
        L = ['# Iteration 85：第十一代——放空流量（借券賣出 ÷ 成交金額）與產業領先股', '',
             f'**產生：** {date.today()}　**腳本：** `AI/experiments/iter85_results.py`　**事前登記：** `AI/experiments/iter85_hypothesis.md`　**N：** {n}（{cnt} 列）；保留期未開。', '']
        L += section_metrics(rows)
        L += section_diag()
        L += section_positions(conn, rows)
    with open(OUT, 'w', encoding='utf-8', newline='') as f:
        f.write('\n'.join(L) + '\n')
    print('寫入', OUT)


if __name__ == '__main__':
    main()
