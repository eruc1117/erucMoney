"""
Iteration 68 結果檔產生器：以營收驚喜為條件的動能（#82 `win3+momrev`）對候選 #30／#38 與 `rev_accel+mom` #53／#62，
以及每個開發期訊號日的候選池大小（股票池、有 `win3+mom` 分數的、有 `win3+momrev` 分數的）。
用法（在 Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter68_results.py
結果檔是證據，不手改。來源：portfolio_runs.metrics；portfolio_signal.eligible／scores_on。
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

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'UnifiedModel', 'results', 'portfolio_iter68_momrev.md')


def pool_sizes() -> list:
    s, e = SEGMENTS['dev']
    mkt = ps.Market(ps.load_prices(s, e), ps.load_universe_meta())
    sur = ps.surprises(ps.load_revenue(s))
    rows = []
    for sd, _ in ps.rebalance_schedule(mkt, s, e):
        ids = ps.eligible(mkt, sd)
        su = ps.signal_sue(sur, sd).reindex(ids)
        rows.append((sd.date(), len(ids), int(su.notna().sum()), int((su > 0).sum()),
                     len(ps.scores_on('win3+mom', mkt, sur, sd, ids)), len(ps.scores_on('win3+momrev', mkt, sur, sd, ids))))
    df = pd.DataFrame(rows, columns=['signal_day', 'eligible', 'sue', 'sue_pos', 'win3+mom', 'win3+momrev']).set_index('signal_day')
    L = ['## 二、開發期每個訊號日的候選池大小（`eligible` 流動性前 300 排除漲停後；池內有當月 SUE／SUE > 0 的；有組合分數的股票數）', '',
         '| 統計 | 股票池 | 池內有 SUE | 池內 SUE > 0 | 有 `win3+mom` 分數 | 有 `win3+momrev` 分數 |', '|---|---|---|---|---|---|']
    for name, fn in (('最小', 'min'), ('中位數', 'median'), ('最大', 'max')):
        v = getattr(df, fn)()
        L.append(f"| {name} | {v['eligible']:.0f} | {v['sue']:.0f} | {v['sue_pos']:.0f} | {v['win3+mom']:.0f} | {v['win3+momrev']:.0f} |")
    L.append('')
    L.append('逐月（股票池／池內有 SUE／池內 SUE > 0／有 `win3+mom` 分數／有 `win3+momrev` 分數；前 10 個月動能歷史不足、組合都 0、不調倉）：')
    L.append('、'.join(f"{d:%Y-%m} {a}/{b}/{c}/{m}/{r}" for d, a, b, c, m, r in
                      zip(df.index, df['eligible'], df['sue'], df['sue_pos'], df['win3+mom'], df['win3+momrev'])))
    L.append('')
    L.append(f"`win3+momrev` 有分數的股票數 < 60 的訊號月：{int((df['win3+momrev'].iloc[10:] < 60).sum())} 個（2018-11 起的 38 個月中）")
    L.append('')
    L.append('SUE 的定義（`surprises`）：YoY 需要 12 個月前的營收、趨勢再往前 3 個月、標準差用前 24 個月（至少 12 個月）——'
             '全市場月營收從 2016-10 起，所以 2019-01 以前只有歷史更長的舊研究股算得出 SUE；事前登記裡「2018-10 起有 1,648 檔 SUE」是錯的：那是對全市場 `sur` 表按月數 `sue` 非空列數的分位數（25% = 174、中位數 = 1,648），被讀成了時間點。')
    return L


def yearly_active(conn) -> list:
    """#30 與 #82 的逐年主動報酬（portfolio_runs.metrics.yearly_active）。"""
    cur = conn.cursor()
    cur.execute("SELECT experiment_n, metrics FROM portfolio_runs WHERE experiment_n = ANY(%s) ORDER BY 1", ([30, 82],))
    rows = cur.fetchall()
    years = sorted({y for _, m in rows for y in (m.get('yearly_active') or {}).keys()})
    if not years:
        return ['## 二之二、逐年主動報酬', '', '（metrics 沒有 yearly_active 欄）']
    L = ['## 二之二、#30 對 #82 的逐年主動報酬（`portfolio_runs.metrics.yearly_active`）', '',
         '| N | ' + ' | '.join(years) + ' |', '|---|' + '---|' * len(years)]
    for n, m in rows:
        ya = m.get('yearly_active') or {}
        L.append(f"| {n} | " + ' | '.join(f"{ya[y]:+.1%}" if y in ya and ya[y] is not None else '' for y in years) + ' |')
    return L


def announce_lag() -> list:
    """有精確公告日的營收（PRECISE_SOURCES，2024-04 起）：反應日晚於當月訊號日的比率——signal_sue 不檢查公告日，這是它的點時缺口大小。"""
    s, e = date(2024, 4, 1), SEGMENTS['holdout'][0]
    mkt = ps.Market(ps.load_prices(date(2024, 1, 1), date(2026, 10, 14)), ps.load_universe_meta())
    sur = ps.surprises(ps.load_revenue(date(2024, 1, 1)))
    x = sur[(sur['revenue_month'] >= pd.Timestamp(s)) & sur['announce_source'].isin(ps.PRECISE_SOURCES) & sur['sue'].notna()].copy()
    sched = {pd.Timestamp(year=sd.year, month=sd.month, day=1): sd for sd, _ in ps.rebalance_schedule(mkt, s, date(2026, 10, 14))}
    late = total = 0
    by_month = {}
    for r in x.itertuples(index=False):
        sd = sched.get(r.revenue_month)
        if sd is None:
            continue
        t0 = ps.reaction_day(r.announce_date, r.announce_ts, mkt.days)
        if t0 is None:
            continue
        total += 1
        is_late = t0 > sd
        late += int(is_late)
        a, b = by_month.get(r.revenue_month, (0, 0))
        by_month[r.revenue_month] = (a + int(is_late), b + 1)
    worst = max(by_month.items(), key=lambda kv: kv[1][0] / kv[1][1]) if by_month else None
    return ['## 四、SUE 的點時缺口：有精確公告日的月份（2024-04 起），反應日晚於當月訊號日的比率（`signal_sue` 不檢查公告日）', '',
            f'- 全市場有 SUE 且公告日精確的股票月：{total}；反應日 > 訊號日：{late}（{late / total:.1%}）' if total else '- 沒有樣本',
            f'- 最高的月份：{worst[0]:%Y-%m}，{worst[1][0]}/{worst[1][1]}（{worst[1][0] / worst[1][1]:.1%}）' if worst else '']


def win3_lunar_new_year() -> list:
    """win3 為空的訊號日（2018-01～2024-09）與每年 2 月 1～11 日的交易日數：農曆年落在 2 月上旬時 win3 的 1～11 日窗口不足 3 天。"""
    s, e = SEGMENTS['dev'][0], SEGMENTS['valid'][1]
    mkt = ps.Market(ps.load_prices(s, e), ps.load_universe_meta())
    empty = [str(sd.date()) for sd, _ in ps.rebalance_schedule(mkt, s, e) if ps.signal_win3(mkt, sd).empty]
    feb = {y: len(mkt.adj.loc[f'{y}-02-01':f'{y}-02-11'].index) for y in range(s.year, e.year + 1)}
    return ['## 三、`win3` 為空的訊號日與每年 2 月 1～11 日的交易日數（`signal_win3`、`rebalance_schedule`，2018-01～2024-09）', '',
            f"- `win3` 為空（組合整個不調倉）的訊號日：{'、'.join(empty) or '無'}",
            '- 2 月 1～11 日交易日數：' + '、'.join(f'{y} 年 {n} 天' for y, n in feb.items()),
            '- `signal_win3` 每個窗口 `sum(min_count=3)`：窗口不足 3 個交易日就 NaN；2 月窗口為 NaN 時，2 月（本月）、3 月（上月）、4 月（上上月）三個訊號日都空']


def revenue_signal_runs(conn) -> list:
    """所有含營收成分（sue／rev_accel／rev_streak／rev_yoy3／momrev／ar0）的實驗：SUE 點時缺口影響的範圍。"""
    cur = conn.cursor()
    cur.execute("SELECT experiment_n, signal, segment FROM portfolio_runs WHERE signal ~ 'sue|rev_accel|rev_streak|rev_yoy3|momrev|ar0' ORDER BY experiment_n")
    rows = cur.fetchall()
    return ['## 五、含營收成分的實驗（`portfolio_runs` 中 signal 含 sue／rev_accel／rev_streak／rev_yoy3／momrev／ar0）', '',
            '、'.join(f"#{n} {sig}（{seg}）" for n, sig, seg in rows), '', f'共 {len(rows)} 列。`ar0` 用精確公告日的反應日，不受這個缺口影響，列出只為完整。']


def main():
    r66.NEW, r66.BASE = [82], [1, 30, 38, 53, 62, 70]
    with get_conn() as conn:
        L = ['# 第三代：以營收驚喜為條件的動能（Iteration 68）', '',
             f'**產生：** {date.today()}（`AI/experiments/iter68_results.py`）', '',
             '事前登記 `AI/experiments/iter68_hypothesis.md`；讀法見 `AI/Doc/Iterations/Iteration-68.md`。', '']
        L += r66.metrics_table(conn) + ['']
        L += pool_sizes() + [''] + yearly_active(conn) + ['']
        L += win3_lunar_new_year() + ['']
        L += announce_lag() + ['']
        L += revenue_signal_runs(conn)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')
    print('寫入', os.path.abspath(OUT))


if __name__ == '__main__':
    main()
