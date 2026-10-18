"""
Iteration 82 結果檔產生器：第十代籌碼結構面（#103 `fhold`、#104 `momlt`、#105 `momsx`、#106 `win3+mom+nsir`、#107 `ndmargin`）對候選 #30 與 `mom` 單獨 #70，
加診斷：兩張表對候選池的覆蓋（流動性名次分桶）、每個訊號日池內有值的股票數（`momsx`／`momlt` 的過濾剩幾檔、`nsir` 池內 SIR＝0 的比例）、各訊號與 `mom` 的等級相關、
前 20 重疊、實際持股的流動性名次與對 #30 的交集（portfolio_positions）、共同窗口（`fhold` 不要歷史、2018-03 就進場）。
用法（在 Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter82_results.py
結果檔是證據，不手改。來源：portfolio_runs.metrics、portfolio_positions、portfolio_run_series、market_margin_daily、market_foreign_holding_daily；
portfolio_signal.eligible／signal_*／scores_on。
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
from db.connection import get_conn  # noqa: E402
import portfolio_signal as ps  # noqa: E402
from portfolio_backtest import SEGMENTS  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'UnifiedModel', 'results', 'portfolio_iter82_chips.md')
NEW = [103, 104, 105, 106, 107]
BASE = [30, 70]
VALID = [38, 108]       # 候選 valid 與 #106 的驗證期一次（#108），只進第一、二節
COLS = [('ann_active', '年化主動', '{:+.2%}'), ('info_ratio', 'IR', '{}'), ('dsr', 'DSR', '{:.3f}'), ('tracking_error', '追蹤誤差', '{:.1%}'),
        ('rel_mdd', '相對最大落後', '{:.1%}'), ('monthly_win_rate', '月勝率', '{:.0%}'), ('turnover_annual', '換手', '{}'),
        ('cost_drag_annual', '成本/年', '{:.2%}'), ('cagr_port', '組合 CAGR', '{:.1%}'), ('cagr_bench', '0050 CAGR', '{:.1%}')]


def metrics_table(conn) -> tuple:
    cur = conn.cursor()
    cur.execute("SELECT experiment_n, name, segment, metrics, n_rebalances, notes, tag FROM portfolio_runs WHERE experiment_n = ANY(%s) ORDER BY experiment_n",
                (NEW + BASE + VALID,))
    rows = cur.fetchall()
    have = [n for n, *_ in rows if n in NEW]
    L = [f'## 一、新實驗（N {min(have)}～{max(have)}）與對照列（`portfolio_runs.metrics`）', '',
         '| N | 設定 | 段 | ' + ' | '.join(c[1] for c in COLS) + ' | 調倉次數 | 備註 |',
         '|---|---|---|' + '---|' * len(COLS) + '---|---|']
    for n, name, seg, m, nreb, notes, tag in rows:
        cells = ['' if m.get(k) is None else fmt.format(m.get(k)) for k, _, fmt in COLS]
        mark = ('對照' if n in BASE or n == 38 else '新') + (f'，tag={tag}' if tag else '')
        L.append(f"| {n} | {name} | {seg} | " + ' | '.join(cells) + f" | {nreb} | {mark} |")
    L += ['', 'DSR 欄是各列跑當時的累積 N 算的，對照列偏高，**不可橫向比**；年化主動、IR、追蹤誤差可以。#70 是 `mom` 單獨（Iteration 66）；#38 是候選的驗證期、#108 是 #106 依登記規則跑的一次驗證期。', '']
    years = sorted({y for *_, m, _, _, _ in rows for y in (m.get('yearly_active') or {})})
    L += ['## 二、逐年主動報酬（`metrics.yearly_active`）', '', '| N | 設定 | ' + ' | '.join(years) + ' |', '|---|---|' + '---|' * len(years)]
    for n, name, seg, m, *_ in rows:
        ya = m.get('yearly_active') or {}
        L.append(f"| {n} | {name} | " + ' | '.join(f"{ya[y]:+.1%}" if ya.get(y) is not None else '' for y in years) + ' |')
    L.append('')
    return L, have


def coverage(conn) -> list:
    cur = conn.cursor()
    cur.execute("""
        WITH p AS (
          SELECT p.stock_id, p.trade_date,
                 rank() OVER (PARTITION BY p.trade_date ORDER BY p.turnover_value DESC NULLS LAST) AS rk,
                 (m.stock_id IS NULL) AS no_margin, (m.stock_id IS NOT NULL AND m.sbl_balance IS NULL) AS no_sbl,
                 (m.sbl_balance = 0) AS sbl_zero, (h.stock_id IS NULL) AS no_hold
          FROM market_daily_prices p
          LEFT JOIN market_margin_daily m USING (stock_id, trade_date)
          LEFT JOIN market_foreign_holding_daily h USING (stock_id, trade_date)
          WHERE p.trade_date BETWEEN %s AND %s AND p.adj_close > 0)
        SELECT CASE WHEN rk <= 300 THEN '1～300' WHEN rk <= 600 THEN '301～600' WHEN rk <= 1000 THEN '601～1000' ELSE '> 1000' END AS bucket,
               count(*) FILTER (WHERE no_margin), count(*) FILTER (WHERE no_sbl), count(*) FILTER (WHERE sbl_zero), count(*) FILTER (WHERE no_hold), count(*)
        FROM p GROUP BY 1 ORDER BY 1""", (SEGMENTS['dev'][0], SEGMENTS['valid'][1]))
    rows = cur.fetchall()
    cur.execute("SELECT count(DISTINCT trade_date), min(trade_date), max(trade_date), count(*), count(*) FILTER (WHERE sbl_balance IS NULL), "
                "count(*) FILTER (WHERE sbl_balance = 0) FROM market_margin_daily")
    mn_days, md0, md1, mn, mn_nosbl, mn_zero = cur.fetchone()
    cur.execute("SELECT count(DISTINCT trade_date), min(trade_date), max(trade_date), count(*) FROM market_foreign_holding_daily")
    hn_days, hd0, hd1, hn = cur.fetchone()
    L = ['## 三、兩張表的覆蓋（2018-01-01～2024-09-30 對 `market_daily_prices`）', '',
         f'`market_margin_daily`：{mn:,} 列、{mn_days} 個交易日、{md0} ~ {md1}；借券欄缺值 {mn_nosbl:,} 列、借券賣出餘額 = 0 的列 {mn_zero:,}（{mn_zero / mn:.1%}）。',
         f'`market_foreign_holding_daily`：{hn:,} 列、{hn_days} 個交易日、{hd0} ~ {hd1}。', '',
         '| 當天成交金額名次 | 有日線沒融資融券列 | 有列但沒借券欄 | 借券餘額 = 0 | 有日線沒外資持股列 | 股票日 | 沒融資融券列比例 | 借券 = 0 比例 | 沒外資持股列比例 |',
         '|---|---|---|---|---|---|---|---|---|']
    for b, nm, ns, z, nh, tot in rows:
        L.append(f'| {b} | {nm:,} | {ns:,} | {z:,} | {nh:,} | {tot:,} | {nm / tot:.1%} | {z / tot:.1%} | {nh / tot:.2%} |')
    L += ['', '候選池是流動性前 300，對應「1～300」那一列（排序把「> 1000」排在最前）。沒有融資融券列 = 沒有信用交易資格（或當天停止信用交易），`sir`／`ndmargin`／`momsx` 都不給值；'
          '借券餘額 = 0 是 `nsir` 的並列；`momsx` 登記時原本只留這群（排除 SIR > 0），池內只有 1%，跑之前改成排除全市場前四分之一（登記檔附錄、`MOMSX_SIR_CUT`）。', '']
    return L


def signal_diag(have: list) -> tuple:
    s, e = SEGMENTS['dev']
    mkt = ps.Market(ps.load_prices(s, e), ps.load_universe_meta())
    mkt.holding = ps.load_holding(s, e)
    mkt.margin = ps.load_margin(s, e)
    sur = ps.surprises(ps.load_revenue(s))
    rows = []
    for sd, _ in ps.rebalance_schedule(mkt, s, e):
        ids = ps.eligible(mkt, sd)
        base = ps.scores_on('win3+mom', mkt, sur, sd, ids)
        if len(base) < 30:
            continue
        mom = ps.signal_mom(mkt, sd).reindex(ids)
        fh = ps.signal_fhold(mkt, sd).reindex(ids)
        sir = ps.signal_sir(mkt, sd).reindex(ids)
        ndm = ps.signal_ndmargin(mkt, sd).reindex(ids)
        tor = ps.signal_tor(mkt, sd)
        tor_pool = tor.reindex(ids)
        momlt = ps.signal_momlt(mkt, sd).reindex(ids)
        momsx = ps.signal_momsx(mkt, sd).reindex(ids)
        rec = {'signal_day': sd.date(), 'n_pool': len(ids), 'n_base': len(base), 'n_mom': int(mom.notna().sum()),
               'n_fhold': int(fh.notna().sum()), 'n_sir': int(sir.notna().sum()), 'sir_zero': float((sir == 0).sum() / max(sir.notna().sum(), 1)),
               'n_ndmargin': int(ndm.notna().sum()), 'n_momlt': int(momlt.notna().sum()), 'n_momsx': int(momsx.notna().sum()),
               'fh_med': float(fh.median()), 'sir_med': float(sir.median()), 'sir_p90': float(sir.quantile(0.9)),
               'tor_med_all': float(tor[tor.index.intersection(ps.signal_mom(mkt, sd).index)].median()), 'tor_med_pool': float(tor_pool.median())}
        for name, x in (('fhold', fh), ('nsir', -sir), ('ndmargin', ndm)):
            both = mom.notna() & x.notna()
            rec[f'rho_{name}'] = float(mom[both].rank().corr(x[both].rank())) if both.sum() >= 30 else np.nan
        top_b = base.sort_values(ascending=False).index[:20]
        sc = ps.scores_on('win3+mom+nsir', mkt, sur, sd, ids)
        rec['n_win3+mom+nsir'] = len(sc)
        rec['top20_win3+mom+nsir'] = len(set(top_b) & set(sc.sort_values(ascending=False).index[:20]))
        rows.append(rec)
    df = pd.DataFrame(rows).set_index('signal_day')
    L = [f'## 四、各訊號在候選池內的覆蓋與和 `mom` 的關係（dev，{len(df)} 個有 win3+mom 分數的訊號日）', '',
         '| 統計 | 股票池 | 有 win3+mom | 有 mom | 有 fhold | 有 sir | 池內 SIR＝0 比例 | 有 ndmargin | momlt 剩 | momsx 剩 | 有 win3+mom+nsir | fhold 中位 % | sir 中位／第 90 分位 % | tor 中位 全市場／池內 %/日 | ρ(mom, fhold) | ρ(mom, nsir) | ρ(mom, ndmargin) | 前 20 重疊 +nsir |',
         '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for name, fn in (('最小', 'min'), ('中位數', 'median'), ('最大', 'max')):
        v = getattr(df, fn)()
        L.append(f"| {name} | {v['n_pool']:.0f} | {v['n_base']:.0f} | {v['n_mom']:.0f} | {v['n_fhold']:.0f} | {v['n_sir']:.0f} | {v['sir_zero']:.0%} | {v['n_ndmargin']:.0f} | "
                 f"{v['n_momlt']:.0f} | {v['n_momsx']:.0f} | {v['n_win3+mom+nsir']:.0f} | {v['fh_med']:.1f} | {v['sir_med']:.2f}／{v['sir_p90']:.2f} | "
                 f"{v['tor_med_all']:.2f}／{v['tor_med_pool']:.2f} | {v['rho_fhold']:.2f} | {v['rho_nsir']:.2f} | {v['rho_ndmargin']:.2f} | {v['top20_win3+mom+nsir']:.0f} |")
    L += ['', 'ρ 是 Spearman 等級相關。`momlt` 用「有 mom 值的全市場股票」的週轉率中位數當門檻（tor 中位「全市場」那欄），所以池內（流動性前 300，週轉率偏高）剩的比一半少；'
          '`momsx` 拿掉 SIR 在全市場（有 mom 又有 sir）前四分之一的、以及沒 sir 值的；池內 SIR 整體偏高（中位數 1.26% 對全市場大半是 0），所以剩的比四分之三少。「有 win3+mom+nsir」少於池，是因為沒有融資融券列的股票沒 `nsir`、排名平均要每個成分都有值。', '']
    return L, mkt


def holdings(conn, mkt, have: list) -> list:
    cur = conn.cursor()
    cur.execute("SELECT r.experiment_n, p.rebalance_date, p.stock_id FROM portfolio_positions p JOIN portfolio_runs r ON r.id = p.run_id "
                "WHERE r.experiment_n = ANY(%s) AND p.filled AND p.stock_id <> %s", ([30] + have, ps.TSMC))
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
    L += ['', '`fhold`／`ndmargin` 不要 252 天歷史，比 #30（2018-11 第一次調倉）早進場；2018 年兩邊不可比，見第七節共同窗口。'
          f'在 2018-10-26 之前的調倉台積電權重用 fallback {ps.TSMC_WEIGHT_FALLBACK}（`estimate_tsmc_weight` 要 200 列全市場資料）。', '',
          '## 六、實際持股的交集（同一調倉日，對 #30；`portfolio_positions.filled`，不含台積電）', '',
          '| 比較 | 調倉日數 | 交集數最小 | 中位數 | 最大 | 兩邊持股數中位數 |', '|---|---|---|---|---|---|']
    g30 = hold[hold['n'] == 30]
    for b in have:
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


def common_window(conn, have: list) -> list:
    """從已存的淨值序列（portfolio_run_series，不重跑、N 不動）算共同窗口的年化主動與 IR：#30 第一次調倉 2018-11-12 起、以及 2019-01-02 起。"""
    cur = conn.cursor()
    cur.execute("""SELECT r.experiment_n, s.trade_date, s.nav, s.bench FROM portfolio_run_series s JOIN portfolio_runs r ON r.id = s.run_id
                   WHERE r.experiment_n = ANY(%s) ORDER BY 1, 2""", ([30, 70] + have,))
    df = pd.DataFrame(cur.fetchall(), columns=['n', 'd', 'nav', 'bench'])
    df['d'] = pd.to_datetime(df['d'])
    L = ['## 七、共同窗口的年化主動與 IR（從 `portfolio_run_series` 算，不重跑；0050 用序列裡的 bench 欄）', '',
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
    L += ['', '與 `portfolio_runs.metrics` 的算法相同（CAGR 差、月主動報酬標準差 × √12）但起點不同，所以 #30／#70 這裡的數字和第一節略有差異（第一節從 2018-01-12 的序列起算、#30 到 2018-11 之前持現金）。', '']
    return L


def main():
    with get_conn() as conn:
        L = ['# Iteration 82 結果：第十代——籌碼結構面（外資持股水準 `fhold`、低週轉率動能 `momlt`、排除被放空股的動能 `momsx`、動能 × 放空反向 `win3+mom+nsir`、散戶融資反向 `ndmargin`）', '',
             '產生：`AI/experiments/iter82_results.py`（2026-10-18）。事前登記：`AI/experiments/iter82_hypothesis.md`（2026-10-18 03:27:30 存檔；`checks.json` `iter82-prereg-mtime`、`iter82-prereg-sha256`），'
             '第一批（`fhold`、`momlt`）03:27:31 起跑、第二批（`momsx`、`win3+mom+nsir`、`ndmargin`）等 `market_margin_daily` 回補完才跑。網格：`iter82_grid.json`，日誌 `iter82_dev.log`。', '']
        mt, have = metrics_table(conn)
        L += mt
        L += coverage(conn)
        diag, mkt = signal_diag(have)
        L += diag
        L += holdings(conn, mkt, have)
        L += common_window(conn, have)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')
    print('寫入', OUT)


if __name__ == '__main__':
    main()
