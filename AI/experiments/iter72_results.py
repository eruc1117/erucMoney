"""
Iteration 72 結果檔產生器：第六代（#89 `win3+mom+indmom`、#90 `win3+relmom`、#91 `win3+mom+seas`、#92 valid）對候選 #30／#38，
加診斷：新成分和 `mom` 的等級相關與前 20 名重疊；#30 對 #90 實際持股的產業集中度（來自 portfolio_positions）；`seas` 每個訊號日可回看的 lag 數。
用法（在 Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter72_results.py
結果檔是證據，不手改。來源：portfolio_runs.metrics、portfolio_positions；portfolio_signal.eligible／signal_*／scores_on。
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

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'UnifiedModel', 'results', 'portfolio_iter72_industry.md')
NEW = [89, 90, 91, 92]
BASE = [30, 38, 70]
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
    L += ['', 'DSR 欄是各列跑當時的累積 N 算的，對照列偏高，**不可橫向比**；年化主動、IR、追蹤誤差可以。', '']
    years = sorted({y for *_, m, _, _, _ in rows for y in (m.get('yearly_active') or {})})
    L += ['## 二、逐年主動報酬（`metrics.yearly_active`）', '', '| N | 設定 | ' + ' | '.join(years) + ' |', '|---|---|' + '---|' * len(years)]
    for n, name, seg, m, *_ in rows:
        ya = m.get('yearly_active') or {}
        L.append(f"| {n} | {name} | " + ' | '.join(f"{ya[y]:+.1%}" if ya.get(y) is not None else '' for y in years) + ' |')
    return L


def signal_diag(segment: str) -> list:
    s, e = SEGMENTS[segment]
    mkt = ps.Market(ps.load_prices(s, e), ps.load_universe_meta())
    sur = ps.surprises(ps.load_revenue(s))
    rows = []
    for sd, _ in ps.rebalance_schedule(mkt, s, e):
        ids = ps.eligible(mkt, sd)
        base = ps.scores_on('win3+mom', mkt, sur, sd, ids)
        if len(base) < 30:
            continue
        mom = ps.signal_mom(mkt, sd).reindex(ids)
        ind = ps._industry_of(mkt, sd)
        rec = {'signal_day': sd.date(), 'n_pool': len(ids), 'n_base': len(base), 'n_noind': int(len(ids.difference(ind.index)))}
        for name, fn in (('indmom', ps.signal_indmom), ('relmom', ps.signal_relmom), ('seas', ps.signal_seas)):
            x = fn(mkt, sd).reindex(ids)
            both = mom.notna() & x.notna()
            rec[f'rho_{name}'] = float(mom[both].rank().corr(x[both].rank())) if both.sum() >= 30 else np.nan
            rec[f'n_{name}'] = int(x.notna().sum())
        top_b = base.sort_values(ascending=False).index[:20]
        for combo in ('win3+mom+indmom', 'win3+relmom', 'win3+mom+seas'):
            top = ps.scores_on(combo, mkt, sur, sd, ids).sort_values(ascending=False).index[:20]
            rec[f'top20_{combo}'] = len(set(top_b) & set(top))
        rows.append(rec)
    df = pd.DataFrame(rows).set_index('signal_day')
    L = [f'## {"三" if segment == "dev" else "四"}、新成分和 `mom` 的關係（{segment}，{len(df)} 個有分數的訊號日，候選池內）', '',
         '| 統計 | 股票池 | 有 win3+mom 分數 | 池內沒有產業別 | ρ(mom, indmom) | ρ(mom, relmom) | ρ(mom, seas) | 池內有 indmom | 池內有 seas | 前 20 重疊 win3+mom+indmom | 前 20 重疊 win3+relmom | 前 20 重疊 win3+mom+seas |',
         '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for name, fn in (('最小', 'min'), ('中位數', 'median'), ('最大', 'max')):
        v = getattr(df, fn)()
        L.append(f"| {name} | {v['n_pool']:.0f} | {v['n_base']:.0f} | {v['n_noind']:.0f} | {v['rho_indmom']:.2f} | {v['rho_relmom']:.2f} | {v['rho_seas']:.2f} | {v['n_indmom']:.0f} | {v['n_seas']:.0f} | "
                 f"{v['top20_win3+mom+indmom']:.0f} | {v['top20_win3+relmom']:.0f} | {v['top20_win3+mom+seas']:.0f} |")
    L += ['', 'ρ 是 Spearman 等級相關；「前 20 重疊」是新組合與 `win3+mom` 各自排名前 20 的交集數（最大 20）。'
          '「池內沒有產業別」的股票（只在下市表、`industry_type` 為空）拿不到 `indmom`／`relmom`，`win3+relmom` 選不到它們而 `win3+mom` 可以。', '']
    if segment == 'valid':
        L.append('這一節是對已跑過的 #92 的描述，**描述性、不得用來設計下一條假設**。')
        L.append('')
    return L


def industry_concentration(conn) -> list:
    """#30／#38 對 #90／#92 實際成交持股（不含台積電）每個調倉日的產業數與最大產業占比。"""
    cur = conn.cursor()
    cur.execute("SELECT r.experiment_n, r.segment, p.rebalance_date, p.stock_id FROM portfolio_positions p JOIN portfolio_runs r ON r.id = p.run_id "
                "WHERE r.experiment_n = ANY(%s) AND p.filled AND p.stock_id <> %s", ([30, 38, 90, 92], ps.TSMC))
    pos = pd.DataFrame(cur.fetchall(), columns=['n', 'segment', 'rebalance_date', 'stock_id'])
    meta = ps.load_universe_meta()
    pos['ind'] = pos['stock_id'].map(meta['industry_type'])
    L = ['## 五、實際持股的產業集中度（`portfolio_positions.filled`，不含台積電；每個調倉日的持股）', '',
         '| N | 段 | 調倉日數 | 持股筆數 | 沒有產業別的持股筆數 | 持股產業數中位數 | 最大產業占比中位數 | 最大產業占比最大 | 最常出現的最大產業 |', '|---|---|---|---|---|---|---|---|---|']
    for n, g in pos.groupby('n'):
        seg = g['segment'].iloc[0]
        per = []
        for d, gg in g.groupby('rebalance_date'):
            vc = gg['ind'].dropna().value_counts()
            per.append((len(vc), vc.iloc[0] / len(gg) if len(vc) else np.nan, vc.index[0] if len(vc) else ''))
        df = pd.DataFrame(per, columns=['n_ind', 'max_share', 'top_ind'])
        L.append(f"| {n} | {seg} | {len(df)} | {len(g)} | {int(g['ind'].isna().sum())} | {df['n_ind'].median():.0f} | {df['max_share'].median():.0%} | {df['max_share'].max():.0%} | {df['top_ind'].mode().iloc[0]} |")
    L += ['', '最大產業占比的分母是當日全部持股（含沒有產業別的）；沒有產業別的持股不算一個產業。', '',
          '### 五之二、實際持股的交集（同一調倉日，#30 對 #90、#38 對 #92；`filled` 持股，不含台積電）', '',
          '| 比較 | 調倉日數 | 交集數最小 | 中位數 | 最大 | 兩邊持股數中位數 |', '|---|---|---|---|---|---|']
    for a, b in ((30, 90), (38, 92)):
        ga, gb = pos[pos['n'] == a], pos[pos['n'] == b]
        days_ = sorted(set(ga['rebalance_date']) & set(gb['rebalance_date']))
        inter, sizes = [], []
        for d in days_:
            sa, sb = set(ga[ga['rebalance_date'] == d]['stock_id']), set(gb[gb['rebalance_date'] == d]['stock_id'])
            inter.append(len(sa & sb))
            sizes.append((len(sa) + len(sb)) / 2)
        s = pd.Series(inter)
        L.append(f"| #{a} 對 #{b} | {len(days_)} | {s.min()} | {s.median():.0f} | {s.max()} | {pd.Series(sizes).median():.0f} |")
    L.append('')
    return L


def seas_lags() -> list:
    """開發期每個訊號日 `seas` 可回看的年數（lag 12／24／36 哪些有資料）。"""
    s, e = SEGMENTS['dev']
    mkt = ps.Market(ps.load_prices(s, e), ps.load_universe_meta())
    days = pd.DatetimeIndex(mkt.days)
    rows = []
    for sd, _ in ps.rebalance_schedule(mkt, s, e):
        k_ok = 0
        for k in (1, 2, 3):
            y, m = sd.year - k, sd.month
            if days.searchsorted(pd.Timestamp(year=y, month=m, day=11)) < len(days) and pd.Timestamp(year=y, month=m, day=11) >= days[0]:
                k_ok += 1
        rows.append((sd.date(), k_ok))
    by_year = pd.DataFrame(rows, columns=['d', 'k']).assign(y=lambda x: [d.year for d in x['d']]).groupby('y')['k'].agg(['min', 'max'])
    L = ['## 六、`seas` 在開發期可回看的 lag 數（每年訊號日的最小～最大）', '', '| 年 | 可用 lag 數 |', '|---|---|']
    for y, r in by_year.iterrows():
        L.append(f"| {y} | {r['min']}～{r['max']} |")
    L += ['', f'全市場日線第一天 {pd.Timestamp(days[0]).date()}；文獻用 20 年的 lag，這裡最多 3 年。', '']
    return L


def industry_counts(conn) -> list:
    cur = conn.cursor()
    cur.execute("SELECT market_type, count(*), count(industry_type), count(DISTINCT industry_type) FROM market_universe GROUP BY 1 ORDER BY 1")
    L = ['## 七、`market_universe` 的產業分類（`industry_type` 依 `market_type`）', '', '| market_type | 股票數 | 有產業別 | 產業類別數 |', '|---|---|---|---|']
    for mt, n, n_ind, n_dist in cur.fetchall():
        L.append(f'| {mt} | {n} | {n_ind} | {n_dist} |')
    L.append('')
    return L


def main():
    with get_conn() as conn:
        L = ['# Iteration 72 結果：第六代——產業動能、扣產業的個股動能、同月季節性', '',
             '產生：`AI/experiments/iter72_results.py`（2026-10-15）。事前登記：`AI/experiments/iter72_hypothesis.md`。網格：`iter72_grid.json`，日誌 `iter72_dev.log`、`iter72_valid.log`。', '']
        L += metrics_table(conn)
        conc = industry_concentration(conn)
        ic = industry_counts(conn)
    L += signal_diag('dev')
    L += signal_diag('valid')
    L += conc
    L += seas_lags()
    L += ic
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')
    print('寫入', OUT)


if __name__ == '__main__':
    main()
