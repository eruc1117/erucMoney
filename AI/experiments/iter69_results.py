"""
Iteration 69 結果檔產生器：文獻第二批第四代（#83 `win3+mom+cont`、#84 `win3+imom`、#85 `win3+mom127`）對候選 #30 與 `mom` #70，
加三個訊號和 `mom` 在開發期每個訊號日的橫斷面相關與前 20 名重疊——用來讀「新成分到底換掉了多少東西」。
用法（在 Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter69_results.py
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

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'UnifiedModel', 'results', 'portfolio_iter69_lit2.md')
NEW = [83, 84, 85]
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
    L += ['', 'DSR 欄是各列跑當時的累積 N 算的（#30 用 N=30、#85 用 N=85），對照列偏高，**不可橫向比**；年化主動、IR、追蹤誤差可以。', '']
    years = sorted({y for *_, m, _, _, _ in rows for y in (m.get('yearly_active') or {})})
    L += ['## 二、逐年主動報酬（`metrics.yearly_active`）', '', '| N | ' + ' | '.join(years) + ' |', '|---|' + '---|' * len(years)]
    for n, name, seg, m, *_ in rows:
        ya = m.get('yearly_active') or {}
        L.append(f"| {n} | " + ' | '.join(f"{ya[y]:+.1%}" if ya.get(y) is not None else '' for y in years) + ' |')
    return L


def signal_overlap() -> list:
    """開發期每個訊號日：新成分與 `mom` 的 Spearman 相關（候選池內）、新組合與候選組合前 20 名的重疊數。"""
    s, e = SEGMENTS['dev']
    mkt = ps.Market(ps.load_prices(s, e), ps.load_universe_meta())
    sur = ps.surprises(ps.load_revenue(s))
    rows = []
    for sd, _ in ps.rebalance_schedule(mkt, s, e):
        ids = ps.eligible(mkt, sd)
        mom = ps.signal_mom(mkt, sd).reindex(ids)
        if mom.notna().sum() < 30:
            continue
        rec = {'signal_day': sd.date()}
        for name, fn in (('cont', ps.signal_cont), ('imom', ps.signal_imom), ('mom127', ps.signal_mom127)):
            x = fn(mkt, sd).reindex(ids)
            both = mom.notna() & x.notna()
            rec[f'rho_{name}'] = float(mom[both].rank().corr(x[both].rank())) if both.sum() >= 30 else np.nan
        base = ps.scores_on('win3+mom', mkt, sur, sd, ids).sort_values(ascending=False).index[:20]
        for combo in ('win3+mom+cont', 'win3+imom', 'win3+mom127'):
            top = ps.scores_on(combo, mkt, sur, sd, ids).sort_values(ascending=False).index[:20]
            rec[f'top20_{combo}'] = len(set(base) & set(top)) if len(base) else np.nan
        rows.append(rec)
    df = pd.DataFrame(rows).set_index('signal_day')
    L = ['## 三、新成分和 `mom` 的關係（開發期有動能分數的訊號日，候選池內）', '',
         '| 統計 | ρ(mom, cont) | ρ(mom, imom) | ρ(mom, mom127) | 前 20 重疊 win3+mom+cont | 前 20 重疊 win3+imom | 前 20 重疊 win3+mom127 |',
         '|---|---|---|---|---|---|---|']
    for name, fn in (('最小', 'min'), ('中位數', 'median'), ('最大', 'max')):
        v = getattr(df, fn)()
        L.append(f"| {name} | {v['rho_cont']:.2f} | {v['rho_imom']:.2f} | {v['rho_mom127']:.2f} | "
                 f"{v['top20_win3+mom+cont']:.0f} | {v['top20_win3+imom']:.0f} | {v['top20_win3+mom127']:.0f} |")
    n_overlap = int(df['top20_win3+imom'].notna().sum())
    L += ['', f'ρ 用 {len(df)} 個訊號日（2018 年動能歷史不足的月份不算）；「前 20 重疊」在 2019-02～04 `win3` 為空的月份是缺值，用 {n_overlap} 個訊號日。'
          'ρ 是 Spearman 等級相關；「前 20 重疊」是新組合與 `win3+mom` 各自排名前 20 的交集數（最大 20）。', '']
    return L


def open_price_coverage(conn) -> list:
    """`imom` 把開盤 ≤ 0 當缺值：數一下全市場日線裡有多少列是這樣。"""
    cur = conn.cursor()
    cur.execute("SELECT count(*) FILTER (WHERE open_price IS NULL OR open_price <= 0), count(*) FROM market_daily_prices "
                "WHERE trade_date BETWEEN '2017-08-01' AND '2024-09-30' AND adj_close > 0")
    bad, total = cur.fetchone()
    cur.execute("SELECT count(*) FILTER (WHERE open_price IS NULL OR open_price <= 0), count(*) FROM stock_daily_prices "
                "WHERE stock_id = %s AND trade_date BETWEEN '2017-08-01' AND '2024-09-30' AND adj_close > 0", (ps.BENCH,))
    bad_b, total_b = cur.fetchone()
    return ['## 四、開盤價缺值（2017-08-01～2024-09-30、`adj_close > 0`）', '',
            f'全市場 `market_daily_prices`：開盤 ≤ 0 或缺值 {bad:,} 列／{total:,} 列（{bad / total:.5%}）。',
            f'0050 `stock_daily_prices`（`ar_intra` 的減項，缺一天全市場那天都缺）：{bad_b:,} 列／{total_b:,} 列。', '']


def main():
    with get_conn() as conn:
        L = ['# Iteration 69 結果：文獻第二批第四代——資訊連續性、日內動能、中期動能', '',
             '產生：`AI/experiments/iter69_results.py`（2026-10-15）。事前登記：`AI/experiments/iter69_hypothesis.md`。網格：`iter69_grid.json`，日誌 `iter69_dev.log`。', '']
        L += metrics_table(conn)
        cov = open_price_coverage(conn)
    L += signal_overlap()
    L += cov
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')
    print('寫入', OUT)


if __name__ == '__main__':
    main()
