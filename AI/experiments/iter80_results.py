"""
Iteration 80 結果檔產生器：第九代價值（#99 `dy`、#100 `ep`、#101 `win3+mom+dy`、#102 `win3+mom+ep`）對候選 #30 與 `mom` 單獨 #70，
加診斷：估值表對候選池的覆蓋、`dy`／`ep` 與 `mom` 的等級相關、池內有值的股票數（ep 把虧損股拿掉）、前 20 重疊、`dy` 橫斷面分位、
實際持股的流動性名次與交集（portfolio_positions）。
用法（在 Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter80_results.py
結果檔是證據，不手改。來源：portfolio_runs.metrics、portfolio_positions、market_valuation_daily；portfolio_signal.eligible／signal_*／scores_on。
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
from db.connection import get_conn  # noqa: E402
import portfolio_signal as ps  # noqa: E402
from portfolio_backtest import SEGMENTS  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'UnifiedModel', 'results', 'portfolio_iter80_value.md')
NEW = [99, 100, 101, 102]
BASE = [30, 70]
COLS = [('ann_active', '年化主動', '{:+.2%}'), ('info_ratio', 'IR', '{}'), ('dsr', 'DSR', '{:.3f}'), ('tracking_error', '追蹤誤差', '{:.1%}'),
        ('rel_mdd', '相對最大落後', '{:.1%}'), ('monthly_win_rate', '月勝率', '{:.0%}'), ('turnover_annual', '換手', '{}'),
        ('cost_drag_annual', '成本/年', '{:.2%}'), ('cagr_port', '組合 CAGR', '{:.1%}'), ('cagr_bench', '0050 CAGR', '{:.1%}')]


def metrics_table(conn) -> list:
    cur = conn.cursor()
    cur.execute("SELECT experiment_n, name, segment, metrics, n_rebalances, notes, tag FROM portfolio_runs WHERE experiment_n = ANY(%s) ORDER BY experiment_n",
                (NEW + BASE,))
    rows = cur.fetchall()
    L = [f'## 一、新實驗（N {min(NEW)}～{max(NEW)}）與對照列（`portfolio_runs.metrics`）', '',
         '| N | 設定 | 段 | ' + ' | '.join(c[1] for c in COLS) + ' | 調倉次數 | 備註 |',
         '|---|---|---|' + '---|' * len(COLS) + '---|---|']
    for n, name, seg, m, nreb, notes, tag in rows:
        cells = ['' if m.get(k) is None else fmt.format(m.get(k)) for k, _, fmt in COLS]
        mark = ('對照' if n in BASE else '新') + (f'，tag={tag}' if tag else '')
        L.append(f"| {n} | {name} | {seg} | " + ' | '.join(cells) + f" | {nreb} | {mark} |")
    L += ['', 'DSR 欄是各列跑當時的累積 N 算的，對照列偏高，**不可橫向比**；年化主動、IR、追蹤誤差可以。#70 是 `mom` 單獨（Iteration 66）。', '']
    years = sorted({y for *_, m, _, _, _ in rows for y in (m.get('yearly_active') or {})})
    L += ['## 二、逐年主動報酬（`metrics.yearly_active`）', '', '| N | 設定 | ' + ' | '.join(years) + ' |', '|---|---|' + '---|' * len(years)]
    for n, name, seg, m, *_ in rows:
        ya = m.get('yearly_active') or {}
        L.append(f"| {n} | {name} | " + ' | '.join(f"{ya[y]:+.1%}" if ya.get(y) is not None else '' for y in years) + ' |')
    L.append('')
    return L


def coverage(conn) -> list:
    cur = conn.cursor()
    cur.execute("""
        WITH p AS (
          SELECT p.stock_id, p.trade_date,
                 rank() OVER (PARTITION BY p.trade_date ORDER BY p.turnover_value DESC NULLS LAST) AS rk,
                 (v.stock_id IS NULL) AS missing, (v.pe IS NULL) AS no_pe, (v.dividend_yield > %s) AS big_dy
          FROM market_daily_prices p
          LEFT JOIN market_valuation_daily v USING (stock_id, trade_date)
          WHERE p.trade_date BETWEEN %s AND %s AND p.adj_close > 0)
        SELECT CASE WHEN rk <= 300 THEN '1～300' WHEN rk <= 600 THEN '301～600' WHEN rk <= 1000 THEN '601～1000' ELSE '> 1000' END AS bucket,
               count(*) FILTER (WHERE missing), count(*) FILTER (WHERE no_pe AND NOT missing), count(*) FILTER (WHERE big_dy), count(*)
        FROM p GROUP BY 1 ORDER BY 1""", (ps.DY_MAX, SEGMENTS['dev'][0], SEGMENTS['valid'][1]))
    rows = cur.fetchall()
    cur.execute("SELECT count(DISTINCT trade_date), min(trade_date), max(trade_date), count(*), count(*) FILTER (WHERE pe IS NULL), "
                "count(*) FILTER (WHERE dividend_yield > %s) FROM market_valuation_daily", (ps.DY_MAX,))
    n_days, d0, d1, n, n_nope, n_big = cur.fetchone()
    L = ['## 三、估值表 `market_valuation_daily` 的覆蓋（2018-01-01～2024-09-30 對 `market_daily_prices`）', '',
         f'表：{n:,} 列、{n_days} 個交易日、{d0} ~ {d1}；本益比缺值（虧損）{n_nope:,} 列、殖利率 > {ps.DY_MAX:.0f}% 的列 {n_big:,}。', '',
         '| 當天成交金額名次 | 有日線沒估值列的股票日 | 有估值列但沒本益比 | 殖利率 > 30% | 股票日 | 缺列比例 | 沒本益比比例 |', '|---|---|---|---|---|---|---|']
    for b, miss, nope, big, tot in rows:
        L.append(f'| {b} | {miss:,} | {nope:,} | {big:,} | {tot:,} | {miss / tot:.2%} | {nope / tot:.1%} |')
    L += ['', '候選池是流動性前 300，對應「1～300」那一列（排序把「> 1000」排在最前）。', '']
    return L


def signal_diag() -> tuple:
    s, e = SEGMENTS['dev']
    mkt = ps.Market(ps.load_prices(s, e), ps.load_universe_meta())
    mkt.val = ps.load_valuation(s, e)
    sur = ps.surprises(ps.load_revenue(s))
    rows = []
    for sd, _ in ps.rebalance_schedule(mkt, s, e):
        ids = ps.eligible(mkt, sd)
        base = ps.scores_on('win3+mom', mkt, sur, sd, ids)
        if len(base) < 30:
            continue
        mom = ps.signal_mom(mkt, sd).reindex(ids)
        dy = ps.signal_dy(mkt, sd).reindex(ids)
        ep = ps.signal_ep(mkt, sd).reindex(ids)
        rec = {'signal_day': sd.date(), 'n_pool': len(ids), 'n_base': len(base), 'n_dy': int(dy.notna().sum()), 'n_ep': int(ep.notna().sum()),
               'dy_p10': float(dy.quantile(0.1)), 'dy_med': float(dy.median()), 'dy_p90': float(dy.quantile(0.9)),
               'ep_med': float(ep.median())}
        for name, x in (('dy', dy), ('ep', ep)):
            both = mom.notna() & x.notna()
            rec[f'rho_{name}'] = float(mom[both].rank().corr(x[both].rank())) if both.sum() >= 30 else np.nan
        top_b = base.sort_values(ascending=False).index[:20]
        for combo in ('win3+mom+dy', 'win3+mom+ep'):
            sc = ps.scores_on(combo, mkt, sur, sd, ids)
            rec[f'n_{combo}'] = len(sc)
            rec[f'top20_{combo}'] = len(set(top_b) & set(sc.sort_values(ascending=False).index[:20]))
        rows.append(rec)
    df = pd.DataFrame(rows).set_index('signal_day')
    L = [f'## 四、`dy`／`ep` 與 `mom` 的關係（dev，{len(df)} 個有分數的訊號日，候選池內）', '',
         '| 統計 | 股票池 | 有 win3+mom 分數 | 池內有 dy | 池內有 ep | 有 win3+mom+dy 分數 | 有 win3+mom+ep 分數 | ρ(mom, dy) | ρ(mom, ep) | dy 第 10／50／90 分位 | ep 中位數 | 前 20 重疊 +dy | 前 20 重疊 +ep |',
         '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for name, fn in (('最小', 'min'), ('中位數', 'median'), ('最大', 'max')):
        v = getattr(df, fn)()
        L.append(f"| {name} | {v['n_pool']:.0f} | {v['n_base']:.0f} | {v['n_dy']:.0f} | {v['n_ep']:.0f} | {v['n_win3+mom+dy']:.0f} | {v['n_win3+mom+ep']:.0f} | "
                 f"{v['rho_dy']:.2f} | {v['rho_ep']:.2f} | {v['dy_p10']:.1f}／{v['dy_med']:.1f}／{v['dy_p90']:.1f} | {v['ep_med']:.3f} | "
                 f"{v['top20_win3+mom+dy']:.0f} | {v['top20_win3+mom+ep']:.0f} |")
    L += ['', 'ρ 是 Spearman 等級相關；`dy` 是交易所殖利率（%），`ep` ＝ 1 ÷ 本益比；分位數是該訊號日候選池內的橫斷面。「有 win3+mom+ep 分數」少於池，是因為虧損股沒有 `ep`、排名平均要每個成分都有值。', '']
    return L, mkt


def holdings(conn, mkt) -> list:
    cur = conn.cursor()
    cur.execute("SELECT r.experiment_n, p.rebalance_date, p.stock_id FROM portfolio_positions p JOIN portfolio_runs r ON r.id = p.run_id "
                "WHERE r.experiment_n = ANY(%s) AND p.filled AND p.stock_id <> %s", ([30] + NEW, ps.TSMC))
    hold = pd.DataFrame(cur.fetchall(), columns=['n', 'rebalance_date', 'stock_id'])
    hold['rebalance_date'] = pd.to_datetime(hold['rebalance_date'])
    L = ['## 五、實際持股的全市場流動性名次（dev；`portfolio_positions.filled`，不含台積電；名次 1 = 全市場 60 日成交金額最大）', '',
         '| N | 持股筆數 | 名次中位數 | 名次 ≤ 50 的比例 | 名次 ≤ 100 的比例 | 名次 > 200 的比例 | 第一次調倉日 | 調倉日數 |', '|---|---|---|---|---|---|---|---|']
    for n, g in hold.groupby('n'):
        ranks = []
        for d, gg in g.groupby('rebalance_date'):
            lr = mkt.liq.loc[d].rank(ascending=False)
            ranks.extend(lr.reindex(gg['stock_id']).dropna().tolist())
        r = pd.Series(ranks)
        L.append(f"| {n} | {len(r)} | {r.median():.0f} | {(r <= 50).mean():.0%} | {(r <= 100).mean():.0%} | {(r > 200).mean():.0%} | {g['rebalance_date'].min().date()} | {g['rebalance_date'].nunique()} |")
    L += ['', '`dy`／`ep` 單獨只要估值列、不要 252 天歷史：#99／#100 從 2018 年初就進場，#30／#101／#102 要到 2018-11；2018 年兩邊不可比。'
          f'#99／#100 在 2018-10-26 之前的調倉台積電權重用 fallback {ps.TSMC_WEIGHT_FALLBACK}（`estimate_tsmc_weight` 要 200 列全市場資料），#30 全部是估計值。', '',
          '## 六、實際持股的交集（同一調倉日，對 #30；`portfolio_positions.filled`，不含台積電）', '',
          '| 比較 | 調倉日數 | 交集數最小 | 中位數 | 最大 | 兩邊持股數中位數 |', '|---|---|---|---|---|---|']
    g30 = hold[hold['n'] == 30]
    for b in NEW:
        gb = hold[hold['n'] == b]
        days_ = sorted(set(g30['rebalance_date']) & set(gb['rebalance_date']))
        inter, sizes = [], []
        for d in days_:
            sa, sb = set(g30[g30['rebalance_date'] == d]['stock_id']), set(gb[gb['rebalance_date'] == d]['stock_id'])
            inter.append(len(sa & sb))
            sizes.append((len(sa) + len(sb)) / 2)
        s = pd.Series(inter)
        L.append(f"| #30 對 #{b} | {len(days_)} | {s.min()} | {s.median():.0f} | {s.max()} | {pd.Series(sizes).median():.0f} |")
    L.append('')
    return L


def otc_exposure(conn) -> list:
    """#99／#101 成交持股裡上櫃股的檔數（`market_universe.market_type`），全期與 1～5 月（櫃買殖利率前視的窗口）分開看。"""
    cur = conn.cursor()
    cur.execute("""SELECT r.experiment_n, p.rebalance_date, count(*) FILTER (WHERE u.market_type = 'tpex'), count(*)
                   FROM portfolio_positions p JOIN portfolio_runs r ON r.id = p.run_id LEFT JOIN market_universe u USING (stock_id)
                   WHERE r.experiment_n = ANY(%s) AND p.filled AND p.stock_id <> %s GROUP BY 1, 2 ORDER BY 1, 2""", ([30, 99, 101], ps.TSMC))
    df = pd.DataFrame(cur.fetchall(), columns=['n', 'd', 'tpex', 'total'])
    df['d'] = pd.to_datetime(df['d'])
    df['early'] = df['d'].dt.month <= 5
    L = ['## 七、成交持股裡的上櫃股（`portfolio_positions.filled` × `market_universe.market_type`，不含台積電）', '',
         '| N | 調倉日數 | 上櫃檔數平均（全期） | 上櫃檔數平均（1～5 月成交日） | 上櫃檔數最大 | 1～5 月的調倉日數 |', '|---|---|---|---|---|---|']
    for n, g in df.groupby('n'):
        L.append(f"| {n} | {len(g)} | {g['tpex'].mean():.1f}／{g['total'].mean():.0f} | {g[g['early']]['tpex'].mean():.1f} | {g['tpex'].max()} | {int(g['early'].sum())} |")
    L += ['', '櫃買檔的殖利率在每年公告前含當年才決議的股利（`val-pit-check-80`）；上櫃持股在 1～5 月成交日的檔數就是 #99／#101 受那個前視影響的曝險上限（`-t3` 分批讓它們再留最多 3 個月）。只是描述，不是校正。', '']
    return L


def common_window(conn) -> list:
    """從已存的淨值序列（portfolio_run_series，不重跑、N 不動）算共同窗口的年化主動與 IR：#30 第一次調倉 2018-11-12 起、以及 2019-01-02 起。"""
    cur = conn.cursor()
    cur.execute("""SELECT r.experiment_n, s.trade_date, s.nav, s.bench FROM portfolio_run_series s JOIN portfolio_runs r ON r.id = s.run_id
                   WHERE r.experiment_n = ANY(%s) ORDER BY 1, 2""", ([30, 99, 100, 101, 102],))
    df = pd.DataFrame(cur.fetchall(), columns=['n', 'd', 'nav', 'bench'])
    df['d'] = pd.to_datetime(df['d'])
    L = ['## 八、共同窗口的年化主動與 IR（從 `portfolio_run_series` 算，不重跑；0050 用序列裡的 bench 欄）', '',
         '| N | 窗口 | 年化主動 | 追蹤誤差 | IR | 月數 |', '|---|---|---|---|---|---|']
    for start, label in (('2018-11-12', '2018-11-12～2021-12-30（#30 第一次調倉起）'), ('2019-01-02', '2019-01-02～2021-12-30')):
        for n, g in df.groupby('n'):
            g = g[g['d'] >= start].set_index('d')
            nav, bench = g['nav'].astype(float), g['bench'].astype(float)
            nav, bench = nav / nav.iloc[0], bench / bench.iloc[0]
            years = (nav.index[-1] - nav.index[0]).days / 365.25
            cagr_p, cagr_b = nav.iloc[-1] ** (1 / years) - 1, bench.iloc[-1] ** (1 / years) - 1
            ann_active = (1 + cagr_p) / (1 + cagr_b) - 1
            m_p, m_b = nav.resample('ME').last().pct_change().dropna(), bench.resample('ME').last().pct_change().dropna()
            m_act = (m_p - m_b).dropna()
            te = float(m_act.std() * np.sqrt(12))
            L.append(f"| {n} | {label} | {ann_active:+.2%} | {te:.1%} | {ann_active / te:.3f} | {len(m_act)} |")
    L += ['', '與 `portfolio_runs.metrics` 的算法相同（CAGR 差、月主動報酬標準差 × √12）但起點不同，所以 #30 這裡的數字和第一節略有差異（第一節從 2018-01-12 的序列起算、#30 到 2018-11 之前持現金）。', '']
    return L


def main():
    with get_conn() as conn:
        L = ['# Iteration 80 結果：第九代——價值（殖利率 `dy`、益本比 `ep`，交易所估值表）', '',
             '產生：`AI/experiments/iter80_results.py`（2026-10-17）。事前登記：`AI/experiments/iter80_hypothesis.md`（2026-10-17 22:55 存檔，跑網格 22:55:57 之前；`checks.json` `iter80-prereg-mtime`、`iter80-prereg-sha256`）。網格：`iter80_grid.json`，日誌 `iter80_dev.log`；valid 依登記的規則沒跑（四條都沒在開發期兩項超過 #30）。', '']
        L += metrics_table(conn)
        L += coverage(conn)
        diag, mkt = signal_diag()
        L += diag
        L += holdings(conn, mkt)
        L += otc_exposure(conn)
        L += common_window(conn)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')
    print('寫入', OUT)


if __name__ == '__main__':
    main()
