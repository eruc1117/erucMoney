"""
Iteration 73 結果檔產生器：第七代法人買賣超（#93 `fflow`、#94 `win3+mom+fflow`、#95 `win3+mom+tflow`、#96 valid）對候選 #30／#38，
加診斷：法人表對候選池的覆蓋率、`fflow`／`tflow` 與 `mom` 的等級相關與前 20 重疊、實際持股交集（portfolio_positions）、`fflow` 的橫斷面分佈。
用法（在 Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter73_results.py
結果檔是證據，不手改。來源：portfolio_runs.metrics、portfolio_positions、market_institutional_daily；portfolio_signal.eligible／signal_*／scores_on。
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
from db.connection import get_conn  # noqa: E402
import portfolio_signal as ps  # noqa: E402
from portfolio_backtest import SEGMENTS  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'UnifiedModel', 'results', 'portfolio_iter73_insti.md')
NEW = [93, 94, 95, 96]
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


def coverage(conn) -> list:
    """法人表對日線的覆蓋：缺列的股票日按當天成交金額名次分桶；全市場 vs 前 300。"""
    cur = conn.cursor()
    cur.execute("""
        WITH p AS (
          SELECT p.stock_id, p.trade_date,
                 rank() OVER (PARTITION BY p.trade_date ORDER BY p.turnover_value DESC NULLS LAST) AS rk,
                 (i.stock_id IS NULL) AS missing
          FROM market_daily_prices p
          LEFT JOIN market_institutional_daily i USING (stock_id, trade_date)
          WHERE p.trade_date BETWEEN %s AND %s AND p.adj_close > 0)
        SELECT CASE WHEN rk <= 300 THEN '1～300' WHEN rk <= 600 THEN '301～600' WHEN rk <= 1000 THEN '601～1000' ELSE '> 1000' END AS bucket,
               count(*) FILTER (WHERE missing), count(*) FROM p GROUP BY 1 ORDER BY 1""", (SEGMENTS['dev'][0], SEGMENTS['valid'][1]))
    rows = cur.fetchall()
    cur.execute("SELECT count(DISTINCT trade_date), min(trade_date), max(trade_date), count(*), "
                "count(*) FILTER (WHERE foreign_net + trust_net + dealer_net <> total_net) FROM market_institutional_daily")
    n_days, d0, d1, n, n_bad = cur.fetchone()
    cur.execute("""SELECT trade_date FROM market_daily_prices WHERE trade_date BETWEEN %s AND %s GROUP BY 1 HAVING count(*) >= 1000
                   EXCEPT SELECT trade_date FROM market_institutional_daily GROUP BY 1 HAVING count(*) >= 800 ORDER BY 1""",
                (SEGMENTS['dev'][0], SEGMENTS['valid'][1]))
    missing_days = [str(r[0]) for r in cur.fetchall()]
    L = ['## 三、法人表 `market_institutional_daily` 的覆蓋（2018-01-01～2024-09-30 對 `market_daily_prices`）', '',
         f'表：{n:,} 列、{n_days} 個交易日、{d0} ~ {d1}；合計 ≠ 三法人相加的列 {n_bad}。日線有而法人表沒有的交易日：{len(missing_days)}{("（" + "、".join(missing_days) + "）") if missing_days else ""}。', '',
         '| 當天成交金額名次 | 有日線沒法人列的股票日 | 股票日 | 比例 |', '|---|---|---|---|']
    for b, miss, tot in rows:
        L.append(f'| {b} | {miss:,} | {tot:,} | {miss / tot:.2%} |')
    L += ['', '候選池是流動性前 300（60 日平均成交金額），對應「1～300」那一列（排序把「> 1000」排在最前）；缺列集中在名次 1,000 以外的股票。', '']
    return L


def signal_diag(segment: str) -> list:
    s, e = SEGMENTS[segment]
    mkt = ps.Market(ps.load_prices(s, e), ps.load_universe_meta())
    mkt.insti = ps.load_institutional(s, e)
    sur = ps.surprises(ps.load_revenue(s))
    rows = []
    for sd, _ in ps.rebalance_schedule(mkt, s, e):
        ids = ps.eligible(mkt, sd)
        base = ps.scores_on('win3+mom', mkt, sur, sd, ids)
        if len(base) < 30:
            continue
        mom = ps.signal_mom(mkt, sd).reindex(ids)
        rec = {'signal_day': sd.date(), 'n_pool': len(ids), 'n_base': len(base)}
        for name, fn in ((('fflow', ps.signal_fflow), ('tflow', ps.signal_tflow)) if segment == 'dev' else (('fflow', ps.signal_fflow),)):
            x = fn(mkt, sd).reindex(ids)
            both = mom.notna() & x.notna()
            rec[f'rho_{name}'] = float(mom[both].rank().corr(x[both].rank())) if both.sum() >= 30 else np.nan
            rec[f'n_{name}'] = int(x.notna().sum())
            if name == 'fflow':
                rec['fflow_med'] = float(x.median())
                rec['fflow_p90'] = float(x.quantile(0.9))
                rec['fflow_p10'] = float(x.quantile(0.1))
        if segment != 'dev':
            rec['rho_tflow'] = np.nan
            rec['n_tflow'] = np.nan
        top_b = base.sort_values(ascending=False).index[:20]
        for combo in (('win3+mom+fflow', 'win3+mom+tflow') if segment == 'dev' else ('win3+mom+fflow',)):
            top = ps.scores_on(combo, mkt, sur, sd, ids).sort_values(ascending=False).index[:20]
            rec[f'top20_{combo}'] = len(set(top_b) & set(top))
        if segment != 'dev':
            rec['top20_win3+mom+tflow'] = np.nan
        rows.append(rec)
    df = pd.DataFrame(rows).set_index('signal_day')
    L = [f'## {"四" if segment == "dev" else "五"}、`fflow`／`tflow` 與 `mom` 的關係（{segment}，{len(df)} 個有分數的訊號日，候選池內）', '',
         '| 統計 | 股票池 | 有 win3+mom 分數 | 池內有 fflow | 池內有 tflow | ρ(mom, fflow) | ρ(mom, tflow) | fflow 第 10 分位 | 中位數 | 第 90 分位 | 前 20 重疊 win3+mom+fflow | 前 20 重疊 win3+mom+tflow |',
         '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for name, fn in (('最小', 'min'), ('中位數', 'median'), ('最大', 'max')):
        v = getattr(df, fn)()
        L.append(f"| {name} | {v['n_pool']:.0f} | {v['n_base']:.0f} | {v['n_fflow']:.0f} | {v['n_tflow']:.0f} | {v['rho_fflow']:.2f} | {v['rho_tflow']:.2f} | "
                 f"{v['fflow_p10']:+.1%} | {v['fflow_med']:+.1%} | {v['fflow_p90']:+.1%} | {v['top20_win3+mom+fflow']:.0f} | {v['top20_win3+mom+tflow']:.0f} |")
    L += ['', 'ρ 是 Spearman 等級相關；`fflow` 是最近 21 日外資淨買超金額（股數 × 收盤）占成交金額的比例，分位數是該訊號日候選池內的橫斷面。', '']
    if segment == 'valid':
        L += ['這一節是對已跑過的 #96 的描述，**描述性、不得用來設計下一條假設**；`tflow` 家族在開發期已關閉、沒在驗證期跑過，所以這一節不算它。', '']
    return L


def holdings_overlap(conn) -> list:
    cur = conn.cursor()
    cur.execute("SELECT r.experiment_n, r.segment, p.rebalance_date, p.stock_id FROM portfolio_positions p JOIN portfolio_runs r ON r.id = p.run_id "
                "WHERE r.experiment_n = ANY(%s) AND p.filled AND p.stock_id <> %s", ([30, 38, 94, 96], ps.TSMC))
    pos = pd.DataFrame(cur.fetchall(), columns=['n', 'segment', 'rebalance_date', 'stock_id'])
    cur.execute("SELECT r.experiment_n, p.rebalance_date, p.stock_id FROM portfolio_positions p JOIN portfolio_runs r ON r.id = p.run_id "
                "WHERE r.experiment_n = ANY(%s) AND p.filled AND p.stock_id <> %s", ([30, 93, 94], ps.TSMC))
    hold = pd.DataFrame(cur.fetchall(), columns=['n', 'rebalance_date', 'stock_id'])
    hold['rebalance_date'] = pd.to_datetime(hold['rebalance_date'])
    s_, e_ = SEGMENTS['dev']
    mkt = ps.Market(ps.load_prices(s_, e_), ps.load_universe_meta())
    L = ['## 六、實際持股的全市場流動性名次（dev；`portfolio_positions.filled`，不含台積電；名次 1 = 全市場 60 日成交金額最大）', '',
         '| N | 持股筆數 | 名次中位數 | 名次 ≤ 50 的比例 | 名次 ≤ 100 的比例 | 第一次調倉日 |', '|---|---|---|---|---|---|']
    for n, g in hold.groupby('n'):
        ranks = []
        for d, gg in g.groupby('rebalance_date'):
            lr = mkt.liq.loc[d].rank(ascending=False)
            ranks.extend(lr.reindex(gg['stock_id']).dropna().tolist())
        r = pd.Series(ranks)
        L.append(f"| {n} | {len(r)} | {r.median():.0f} | {(r <= 50).mean():.0%} | {(r <= 100).mean():.0%} | {g['rebalance_date'].min().date()} |")
    L += ['', '`fflow` 只要 22 天歷史、`mom` 要 252 天：#93 從 2018 年初就進場，#30／#94 要到 2018 年底；2018 年兩邊不可比。', '',
          '## 七、實際持股的交集（同一調倉日，#30 對 #94、#38 對 #96；`portfolio_positions.filled`，不含台積電）', '',
         '| 比較 | 調倉日數 | 交集數最小 | 中位數 | 最大 | 兩邊持股數中位數 |', '|---|---|---|---|---|---|']
    for a, b in ((30, 94), (38, 96)):
        ga, gb = pos[pos['n'] == a], pos[pos['n'] == b]
        days_ = sorted(set(ga['rebalance_date']) & set(gb['rebalance_date']))
        if not days_:
            L.append(f'| #{a} 對 #{b} | 0（#{b} 沒跑） | | | | |')
            continue
        inter, sizes = [], []
        for d in days_:
            sa, sb = set(ga[ga['rebalance_date'] == d]['stock_id']), set(gb[gb['rebalance_date'] == d]['stock_id'])
            inter.append(len(sa & sb))
            sizes.append((len(sa) + len(sb)) / 2)
        s = pd.Series(inter)
        L.append(f"| #{a} 對 #{b} | {len(days_)} | {s.min()} | {s.median():.0f} | {s.max()} | {pd.Series(sizes).median():.0f} |")
    L.append('')
    return L


def main():
    with get_conn() as conn:
        L = ['# Iteration 73 結果：第七代——法人買賣超（外資、投信）', '',
             '產生：`AI/experiments/iter73_results.py`（2026-10-16）。事前登記：`AI/experiments/iter73_hypothesis.md`（2026-10-15 23:20 寫的，當時回補到 2021-01、還沒看任何法人數字）。網格：`iter73_grid.json`，日誌 `iter73_dev.log`、`iter73_valid.log`；回補日誌 `iter71_backfill.log`。', '']
        L += metrics_table(conn)
        L += coverage(conn)
        ov = holdings_overlap(conn)
    L += signal_diag('dev')
    L += signal_diag('valid')
    L += ov
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')
    print('寫入', OUT)


if __name__ == '__main__':
    main()
