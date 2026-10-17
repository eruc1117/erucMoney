"""
Iteration 78 結果檔產生器：第八代波動處理的動能（#97 `win3+vmom`、#98 `win3+momx`）對候選 #30，
加診斷：`vmom`／`momx` 與 `mom` 的等級相關、候選池內被 `momx` 排除的比例、前 20 重疊、實際持股交集與流動性名次（portfolio_positions）。
用法（在 Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter78_results.py
結果檔是證據，不手改。來源：portfolio_runs.metrics、portfolio_positions、market_daily_prices；portfolio_signal.eligible／signal_*／scores_on。
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
from db.connection import get_conn  # noqa: E402
import portfolio_signal as ps  # noqa: E402
from portfolio_backtest import SEGMENTS  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'UnifiedModel', 'results', 'portfolio_iter78_volmom.md')
NEW = [97, 98]
BASE = [30, 51]
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
    L += ['', 'DSR 欄是各列跑當時的累積 N 算的，對照列偏高，**不可橫向比**；年化主動、IR、追蹤誤差可以。#51 是 Iteration 53 的 `win3+mom+lowvol`（低波動**相加**），放進來對照「相加」與「除以／排除」的差別。', '']
    years = sorted({y for *_, m, _, _, _ in rows for y in (m.get('yearly_active') or {})})
    L += ['## 二、逐年主動報酬（`metrics.yearly_active`）', '', '| N | 設定 | ' + ' | '.join(years) + ' |', '|---|---|' + '---|' * len(years)]
    for n, name, seg, m, *_ in rows:
        ya = m.get('yearly_active') or {}
        L.append(f"| {n} | {name} | " + ' | '.join(f"{ya[y]:+.1%}" if ya.get(y) is not None else '' for y in years) + ' |')
    L.append('')
    return L


def signal_diag() -> list:
    s, e = SEGMENTS['dev']
    mkt = ps.Market(ps.load_prices(s, e), ps.load_universe_meta())
    sur = ps.surprises(ps.load_revenue(s))
    rows = []
    for sd, _ in ps.rebalance_schedule(mkt, s, e):
        ids = ps.eligible(mkt, sd)
        base = ps.scores_on('win3+mom', mkt, sur, sd, ids)
        if len(base) < 30:
            continue
        mom = ps.signal_mom(mkt, sd).reindex(ids)
        vm = ps.signal_vmom(mkt, sd).reindex(ids)
        mx = ps.signal_momx(mkt, sd).reindex(ids)
        m_all, sd_all = ps._mom_and_vol(mkt, sd)
        both = mom.notna() & vm.notna()
        vol = sd_all.reindex(ids)
        bv = mom.notna() & vol.notna()
        rec = {'signal_day': sd.date(), 'n_pool': len(ids), 'n_base': len(base), 'n_mom': int(mom.notna().sum()), 'n_momx': int(mx.notna().sum()),
               'excl_pool': 1 - mx.notna().sum() / max(mom.notna().sum(), 1),
               'rho_vmom': float(mom[both].rank().corr(vm[both].rank())) if both.sum() >= 30 else np.nan,
               'rho_vol': float(mom[bv].rank().corr(vol[bv].rank())) if bv.sum() >= 30 else np.nan,
               'vol_med_pool': float(sd_all.reindex(ids).median()), 'vol_med_all': float(sd_all.median()),
               'vol_cut_all': float(sd_all[m_all.notna() & sd_all.notna()].quantile(ps.MOMX_VOL_CUT))}
        top_b = base.sort_values(ascending=False).index[:20]
        for combo in ('win3+vmom', 'win3+momx'):
            top = ps.scores_on(combo, mkt, sur, sd, ids).sort_values(ascending=False).index[:20]
            rec[f'top20_{combo}'] = len(set(top_b) & set(top))
        rows.append(rec)
    df = pd.DataFrame(rows).set_index('signal_day')
    L = [f'## 三、`vmom`／`momx` 與 `mom` 的關係（dev，{len(df)} 個有分數的訊號日，候選池內）', '',
         '| 統計 | 股票池 | 有 win3+mom 分數 | 池內有 mom | 池內有 momx | 池內被 momx 排除的比例 | ρ(mom, vmom) | ρ(mom, vol) | 池內波動中位數（日） | 全市場波動中位數（日） | 全市場第 90 分位（排除線） | 前 20 重疊 win3+vmom | 前 20 重疊 win3+momx |',
         '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for name, fn in (('最小', 'min'), ('中位數', 'median'), ('最大', 'max')):
        v = getattr(df, fn)()
        L.append(f"| {name} | {v['n_pool']:.0f} | {v['n_base']:.0f} | {v['n_mom']:.0f} | {v['n_momx']:.0f} | {v['excl_pool']:.0%} | {v['rho_vmom']:.2f} | {v['rho_vol']:.2f} | "
                 f"{v['vol_med_pool']:.2%} | {v['vol_med_all']:.2%} | {v['vol_cut_all']:.2%} | {v['top20_win3+vmom']:.0f} | {v['top20_win3+momx']:.0f} |")
    L += ['', 'ρ 是 Spearman 等級相關；波動是 `mom` 同一個 12-1 窗口內每日異常報酬（對 0050）的標準差。`momx` 的排除線在全市場（有 mom 值的股票，含窗口內資料足夠但 d 之前已下市的）算，所以池內（流動性前 300）被排除的比例不是剛好 10%。', '']
    L += excluded_forward(mkt, sur)
    return L, mkt


def excluded_forward(mkt, sur) -> list:
    """每個訊號日：候選 `win3+mom` 前 20 裡被 `momx` 排除的股票，對留下的股票，之後到下一個訊號日的累積異常報酬（等權平均）。分年彙總。"""
    s, e = SEGMENTS['dev']
    sched = ps.rebalance_schedule(mkt, s, e)
    rows = []
    for k, (sd, _) in enumerate(sched):
        ids = ps.eligible(mkt, sd)
        base = ps.scores_on('win3+mom', mkt, sur, sd, ids)
        if len(base) < 30:
            continue
        top = list(base.sort_values(ascending=False).index[:20])
        mx = ps.signal_momx(mkt, sd)
        excl = [t for t in top if t not in mx.index]
        kept = [t for t in top if t in mx.index]
        nxt = sched[k + 1][0] if k + 1 < len(sched) else mkt.adj.index[-1]
        i0 = int(np.searchsorted(mkt.days, np.datetime64(sd), side='right'))      # 成交日起
        i1 = int(np.searchsorted(mkt.days, np.datetime64(nxt), side='right'))
        fwd = mkt.ar.iloc[i0:i1].sum(min_count=1)
        rows.append({'year': sd.year, 'signal_day': sd.date(), 'n_excl': len(excl),
                     'fwd_excl': float(fwd.reindex(excl).mean()) if excl else np.nan, 'fwd_kept': float(fwd.reindex(kept).mean()) if kept else np.nan})
    df = pd.DataFrame(rows)
    L = ['## 六、候選前 20 裡被 `momx` 排除的股票，之後一個月的異常報酬（dev；對同一天留下的股票）', '',
         '| 年 | 訊號日數 | 每天被排除的檔數（平均） | 被排除者下月異常報酬（平均） | 留下者下月異常報酬（平均） | 差（排除 − 留下） |', '|---|---|---|---|---|---|']
    for y, g in df.groupby('year'):
        L.append(f"| {y} | {len(g)} | {g['n_excl'].mean():.1f} | {g['fwd_excl'].mean():+.2%} | {g['fwd_kept'].mean():+.2%} | {(g['fwd_excl'] - g['fwd_kept']).mean():+.2%} |")
    L.append(f"| 全期 | {len(df)} | {df['n_excl'].mean():.1f} | {df['fwd_excl'].mean():+.2%} | {df['fwd_kept'].mean():+.2%} | {(df['fwd_excl'] - df['fwd_kept']).mean():+.2%} |")
    L += ['', '「下一個月」＝訊號日次日起到下一個訊號日（含）的每日異常報酬累加（對 0050，不含成本）；被排除者是候選會買、`momx` 版不會買的那幾檔。只是描述，不是新假設。', '']
    return L


def holdings(conn, mkt) -> list:
    cur = conn.cursor()
    cur.execute("SELECT r.experiment_n, p.rebalance_date, p.stock_id FROM portfolio_positions p JOIN portfolio_runs r ON r.id = p.run_id "
                "WHERE r.experiment_n = ANY(%s) AND p.filled AND p.stock_id <> %s", ([30] + NEW, ps.TSMC))
    hold = pd.DataFrame(cur.fetchall(), columns=['n', 'rebalance_date', 'stock_id'])
    hold['rebalance_date'] = pd.to_datetime(hold['rebalance_date'])
    L = ['## 四、實際持股的全市場流動性名次（dev；`portfolio_positions.filled`，不含台積電；名次 1 = 全市場 60 日成交金額最大）', '',
         '| N | 持股筆數 | 名次中位數 | 名次 ≤ 50 的比例 | 名次 ≤ 100 的比例 | 名次 > 200 的比例 | 第一次調倉日 |', '|---|---|---|---|---|---|---|']
    for n, g in hold.groupby('n'):
        ranks = []
        for d, gg in g.groupby('rebalance_date'):
            lr = mkt.liq.loc[d].rank(ascending=False)
            ranks.extend(lr.reindex(gg['stock_id']).dropna().tolist())
        r = pd.Series(ranks)
        L.append(f"| {n} | {len(r)} | {r.median():.0f} | {(r <= 50).mean():.0%} | {(r <= 100).mean():.0%} | {(r > 200).mean():.0%} | {g['rebalance_date'].min().date()} |")
    L += ['', '## 五、實際持股的交集（同一調倉日，#30 對 #97、#30 對 #98；`portfolio_positions.filled`，不含台積電）', '',
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


def main():
    with get_conn() as conn:
        L = ['# Iteration 78 結果：第八代——波動處理的動能（`vmom`、`momx`）', '',
             '產生：`AI/experiments/iter78_results.py`（2026-10-17）。事前登記：`AI/experiments/iter78_hypothesis.md`（2026-10-17 20:20 寫的，跑網格前）。網格：`iter78_grid.json`，日誌 `iter78_dev.log`；valid 依登記的規則沒跑（兩條都沒在開發期超過 #30）。', '']
        L += metrics_table(conn)
        diag, mkt = signal_diag()
        L += diag
        L += holdings(conn, mkt)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')
    print('寫入', OUT)


if __name__ == '__main__':
    main()
