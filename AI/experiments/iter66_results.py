"""
Iteration 66 結果檔產生器：從 portfolio_runs 讀第三批（文獻假設）實驗與對照列，輸出 Markdown 到 UnifiedModel/results。
用法（在 Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter66_results.py
結果檔是證據，不手改。三節的來源：
    1. 指標表：portfolio_runs.metrics
    2. 市場狀態閘門的訊號月：對開發期／驗證期每個調倉訊號日呼叫 portfolio_signal.market_state_up（用 load_prices 載的 0050）
    3. #30 對 #75 的逐月主動報酬：portfolio_run_series（nav／bench 月底值）
"""
import os
import sys
from datetime import date

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
from db.connection import get_conn  # noqa: E402
import portfolio_signal as ps  # noqa: E402
from portfolio_backtest import SEGMENTS  # noqa: E402

NEW = list(range(70, 81))
BASE = [21, 30, 38, 34, 42, 45, 46, 49, 55, 58]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'UnifiedModel', 'results', 'portfolio_iter66_papers.md')

COLS = [('ann_active', '年化主動', '{:+.2%}'), ('info_ratio', 'IR', '{}'), ('dsr', 'DSR', '{:.3f}'), ('tracking_error', '追蹤誤差', '{:.1%}'),
        ('rel_mdd', '相對最大落後', '{:.1%}'), ('monthly_win_rate', '月勝率', '{:.0%}'), ('turnover_annual', '換手', '{}'),
        ('cost_drag_annual', '成本/年', '{:.2%}'), ('cagr_port', '組合 CAGR', '{:.1%}'), ('cagr_bench', '0050 CAGR', '{:.1%}')]


def metrics_table(conn) -> list:
    cur = conn.cursor()
    cur.execute("SELECT experiment_n, name, signal, segment, period_start, period_end, metrics, n_rebalances, notes, tag "
                "FROM portfolio_runs WHERE experiment_n = ANY(%s) ORDER BY experiment_n", (NEW + BASE,))
    L = [f'## 一、新實驗（N {min(NEW)}～{max(NEW)}）與對照列（`portfolio_runs.metrics`）', '',
         '| N | 設定 | 段 | ' + ' | '.join(c[1] for c in COLS) + ' | 調倉次數 | 備註 |',
         '|---|---|---|' + '---|' * len(COLS) + '---|---|']
    for n, name, signal, seg, ps_, pe, m, nreb, notes, tag in cur.fetchall():
        cells = ['' if m.get(k) is None else fmt.format(m.get(k)) for k, _, fmt in COLS]
        mark = '對照' if n in BASE else '新'
        if n in (71, 72, 76):
            mark = '新（實作錯誤：帶截距 OLS，等於一個月殘差反轉）'
        if tag:
            mark += f'，tag={tag}'
        if tag == 'void':
            mark += '；notes 末段：「' + (notes or '')[-70:] + '」'
        L.append(f"| {n} | {name} | {seg} | " + ' | '.join(cells) + f" | {nreb} | {mark} |")
    L.append('')
    L.append('DSR 欄是各列跑當時的累積 N 算的（#30 用 N=30、#80 用 N=80），對照列偏高，**不可橫向比**；年化主動、IR、追蹤誤差可以。')
    return L


def gate_months() -> list:
    L = ['## 二、市場狀態閘門（`~up`）的訊號月：`market_state_up`（0050 過去 252 日報酬 < 0 為 DOWN）對每個調倉訊號日計算', '']
    meta = ps.load_universe_meta()
    for seg in ('dev', 'valid'):
        s, e = SEGMENTS[seg]
        mkt = ps.Market(ps.load_prices(s, e), meta)
        states = [(sd.date(), ps.market_state_up(mkt, sd)) for sd, _ in ps.rebalance_schedule(mkt, s, e)]
        down = [str(d) for d, u in states if u is False]
        none = [str(d) for d, u in states if u is None]
        L.append(f'- {seg}：{len(states)} 個訊號日；DOWN {len(down)} 個：{"、".join(down)}；歷史不足（不閘門）{len(none)} 個：{none[0]}～{none[-1]}')
    return L


def monthly_compare(conn, a: int = 30, b: int = 75, start: str = '2018-09', end: str = '2019-10') -> list:
    """兩個 run 的逐月主動報酬（組合月報酬 − 0050 月報酬，月底 nav）。"""
    df = pd.read_sql("SELECT r.experiment_n AS n, s.trade_date, s.nav, s.bench FROM portfolio_run_series s JOIN portfolio_runs r ON r.id = s.run_id "
                     "WHERE r.experiment_n = ANY(%s) ORDER BY s.trade_date", conn, params=([a, b],))
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    out = {}
    for n, g in df.groupby('n'):
        g = g.set_index('trade_date').sort_index()
        me = g[['nav', 'bench']].resample('ME').last()
        act = me['nav'].pct_change() - me['bench'].pct_change()
        out[n] = act
    tab = pd.concat(out, axis=1).loc[start:end]
    L = [f'## 三、#{a} 對 #{b} 的逐月主動報酬（`portfolio_run_series` 月底 nav／bench，{start}～{end}）', '',
         f'| 月 | #{a} 主動 | #{b} 主動 | 差（#{b} − #{a}） |', '|---|---|---|---|']
    for d, row in tab.iterrows():
        L.append(f"| {d:%Y-%m} | {row[a]:+.2%} | {row[b]:+.2%} | {row[b] - row[a]:+.2%} |")
    L.append(f"| 合計（算術和） | {tab[a].sum():+.2%} | {tab[b].sum():+.2%} | {(tab[b] - tab[a]).sum():+.2%} |")
    return L


def main():
    with get_conn() as conn:
        L = ['# 第三批實驗：文獻假設（Iteration 66）', '',
             f'**產生：** {date.today()}（`AI/experiments/iter66_results.py`）', '',
             '假設與文獻見 `AI/Doc/Papers.md` 第五節；結論見 `AI/Doc/Iterations/Iteration-66.md`。',
             '結構全部固定：分三批、持台積電（估計權重）、流動性前 300、前 20 等權、排除漲停前 10%。', '']
        L += metrics_table(conn) + ['']
        L += gate_months() + ['']
        L += monthly_compare(conn)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')
    print('寫入', os.path.abspath(OUT))


if __name__ == '__main__':
    main()
