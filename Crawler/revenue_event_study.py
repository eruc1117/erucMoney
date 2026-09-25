"""
月營收事件研究（Iteration 39，新聞訊號研究方案階段 1）
────────────────────────────────────────────────────────
方案的核心主張：先做「排程型」新聞。月營收每年 12 次、公布時點可考、意外程度是純數值，
不需要任何 NLP 就能直接檢驗整份方案賴以成立的 PEAD（公布後漂移）假設。

事件與意外程度
    · 事件 = (股票, 營收月份)，公布時點來自 stock_revenue_announce（backfill_revenue_dates.py 合成）。
      有 announce_ts 的用 13:30 規則歸屬交易日；只有日期的一律視為收盤後（有時間戳的樣本 9 成以上如此，
      比例在報告裡印出）→ 下一交易日為 t=0。
    · 意外程度 surprise = YoY − 近 3 個月 YoY 均值（季節性隨機漫步＋趨勢；log 差）。
      SUE = surprise ÷ 該股過去 24 個月 surprise 的標準差（至少 12 個月，不足用全樣本）。
      五分組按 SUE 全樣本切（26 檔每月只有二十幾個事件，逐月橫斷面切太薄）。
    · AR = 個股 log 報酬 − 0050 log 報酬（市場調整；專案沒有加權指數）。
      視窗 [-10, +60]。注意 +20 之後會與下一次月營收重疊，主結論看 CAR[1,20]。

方案的四道關卡在這裡的對應
    N0 時間戳       announce_source 分布與 13:30 後比例
    N1 t+1 後漂移   Q5−Q1 的 CAR[1,5] / [1,10] / [1,20]；事件時間 t 值 + 日曆時間投資組合 t 值（處理同日叢集）
    N2 增量         面板迴歸 CAR[1,20] ~ SUE + 事件前動能 + 60 日動能 + 異常成交量（月份固定效果、按月份叢集 SE）
    N3 漲跌停       t=0 或 t=+1 鎖漲跌停（|漲跌幅| ≥ 9.5% 且收在最高／最低）另計，報告含與不含

輸出：AI/Doc/RevenueEventStudy.md（覆蓋）＋主控台。

用法：
    python revenue_event_study.py [--since 2023-09-01] [--sources cnyes_list,cnyes_item,...] [--min-history 12]
"""

import argparse
import math
import os
import warnings
from datetime import date, datetime, time as dtime, timedelta

import numpy as np
import pandas as pd

from db.connection import get_conn

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'AI', 'Doc', 'RevenueEventStudy.md')
BENCH = '0050'
PRE, POST = 10, 60
HORIZONS = [1, 5, 10, 20, 40, 60]
LIMIT_PCT = 9.5
CLOSE_TW = dtime(13, 30)


# ── 資料 ──────────────────────────────────────────────────────────────────────
def universe(research: bool) -> list:
    """追蹤股（非 ETF）；--research 再加上 research_daily_prices 有價格的研究股（research_universe.py）。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stock_id FROM stock_info WHERE is_tracking AND COALESCE(industry_type, '') <> 'ETF' ORDER BY 1")
            ids = [r[0] for r in cur.fetchall()]
            if research:
                cur.execute("SELECT stock_id FROM research_daily_prices GROUP BY 1 HAVING count(*) >= 200 ORDER BY 1")
                ids += [r[0] for r in cur.fetchall() if r[0] not in ids]
    return ids


def load_prices(stocks: list, since: date) -> pd.DataFrame:
    """追蹤股從 stock_daily_prices（有 adj_close），研究股從 research_daily_prices（未還原，除息日會有一次小跳空）。"""
    with get_conn() as conn:
        main = pd.read_sql("""
            SELECT stock_id, trade_date, COALESCE(adj_close, close_price) AS px,
                   close_price, high_price, low_price, change_rate, volume
            FROM stock_daily_prices WHERE stock_id = ANY(%s) AND trade_date >= %s ORDER BY stock_id, trade_date
        """, conn, params=(stocks, since))
        rest = [s for s in stocks if s not in set(main.stock_id)]
        if rest:
            try:
                extra = pd.read_sql("""
                    SELECT stock_id, trade_date, close_price AS px, close_price, high_price, low_price, change_rate, volume
                    FROM research_daily_prices WHERE stock_id = ANY(%s) AND trade_date >= %s ORDER BY stock_id, trade_date
                """, conn, params=(rest, since))
                main = pd.concat([main, extra], ignore_index=True)
            except Exception:      # noqa: BLE001  表不存在
                pass
    return main


def load_revenue(stocks: list) -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql("""
            SELECT stock_id, revenue_month, revenue, announce_date, announce_ts, announce_source
            FROM stock_revenue_announce WHERE stock_id = ANY(%s) AND revenue IS NOT NULL
            ORDER BY stock_id, revenue_month
        """, conn, params=(stocks,))
    df['revenue_month'] = pd.to_datetime(df.revenue_month)
    return df


def surprises(rev: pd.DataFrame, min_history: int) -> pd.DataFrame:
    """每檔用完整月序列（缺月補 NaN）算 YoY、趨勢與 SUE。"""
    out = []
    for sid, g in rev.groupby('stock_id'):
        s = g.set_index('revenue_month').revenue.astype(float)
        s = s.where(s > 0)
        idx = pd.date_range(s.index.min(), s.index.max(), freq='MS')
        s = s.reindex(idx)
        lg = np.log(s)
        yoy = lg - lg.shift(12)
        trend = pd.concat([yoy.shift(k) for k in (1, 2, 3)], axis=1).mean(axis=1, skipna=False)
        sur = yoy - trend
        mom_sa = (lg - lg.shift(1)) - (lg.shift(12) - lg.shift(13))   # 季節調整後月增，備用維度
        sd = sur.shift(1).rolling(24, min_periods=min_history).std()
        sue = sur / sd
        df = pd.DataFrame({'stock_id': sid, 'yoy': yoy, 'surprise': sur, 'mom_sa': mom_sa, 'sue': sue})
        df.index.name = 'revenue_month'
        out.append(df.reset_index())
    res = pd.concat(out, ignore_index=True)
    return res.merge(rev[['stock_id', 'revenue_month', 'announce_date', 'announce_ts', 'announce_source']],
                     on=['stock_id', 'revenue_month'], how='left')


def event_day(row, open_days: list, pos: dict) -> date | None:
    """公布時點 → t=0 交易日。有時間戳：13:30 前歸當日、否則下一交易日；只有日期：視為收盤後。"""
    if pd.isna(row.announce_date):
        return None
    ts = row.announce_ts
    if pd.notna(ts):
        ts = pd.Timestamp(ts).to_pydatetime()
        d = ts.date()
        if ts.time() < CLOSE_TW and d in pos:
            return d
        after = d
    else:
        after = pd.Timestamp(row.announce_date).date()
    i = np.searchsorted(open_days, after, side='right')      # 第一個 > after 的交易日
    return open_days[i] if i < len(open_days) else None


# ── 統計 ──────────────────────────────────────────────────────────────────────
def tstat(x) -> float:
    x = pd.Series(x).dropna()
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else float('nan')


def calendar_time_t(ar: pd.DataFrame, ev: pd.DataFrame, hold: int, long_q: int, short_q: int) -> tuple:
    """日曆時間投資組合：每天持有「事件後 1..hold 日內」的 Q_long 等權 − Q_short 等權；t 值來自日序列。"""
    idx = list(ar.index)
    legs = {q: pd.DataFrame(0.0, index=ar.index, columns=['sum', 'n']) for q in (long_q, short_q)}
    for e in ev.itertuples(index=False):
        if e.q not in legs:
            continue
        i = e.i
        seg = ar[e.stock_id].iloc[i + 1:i + 1 + hold]
        seg = seg.dropna()
        legs[e.q].loc[seg.index, 'sum'] += seg.values
        legs[e.q].loc[seg.index, 'n'] += 1
    port = {q: (v['sum'] / v['n'].replace(0, np.nan)) for q, v in legs.items()}
    spread = (port[long_q] - port[short_q]).dropna()
    if len(spread) < 10:
        return float('nan'), float('nan'), len(spread)
    daily = spread.mean()
    return daily * hold, float(daily / (spread.std(ddof=1) / math.sqrt(len(spread)))), len(spread)


def cluster_ols(y: np.ndarray, X: np.ndarray, groups: np.ndarray) -> tuple:
    """OLS + 按 groups 叢集的穩健標準誤。回傳 (beta, se)。X 已含截距或已去均值。"""
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    resid = y - X @ beta
    meat = np.zeros((X.shape[1], X.shape[1]))
    for g in np.unique(groups):
        m = groups == g
        u = X[m].T @ resid[m]
        meat += np.outer(u, u)
    G = len(np.unique(groups))
    n, k = X.shape
    adj = G / (G - 1) * (n - 1) / (n - k) if G > 1 and n > k else 1.0
    V = adj * XtX_inv @ meat @ XtX_inv
    return beta, np.sqrt(np.diag(V))


def incremental_regression(st: pd.DataFrame, dep: str = 'car_1_20') -> list:
    """CAR[1,20] ~ SUE + 事件前 CAR[-10,-1] + 60 日動能 + 異常成交量，月份固定效果（去均值）、按月份叢集。"""
    cols = ['sue', 'pre_car', 'mom60', 'abn_vol']
    d = st.dropna(subset=[dep] + cols).copy()
    if len(d) < 50:
        return []
    d['ym'] = pd.to_datetime(d.t0).dt.to_period('M').astype(str)
    dm = d[[dep] + cols].groupby(d.ym).transform(lambda s: s - s.mean())
    specs = [('只有 SUE', ['sue']),
             ('SUE + 動能 + 成交量', cols),
             ('SUE + AR₀（漂移是否延續首日反應）', ['sue', 'ar0']),
             ('AR₀ 單獨', ['ar0'])]
    out = []
    for name, xs in specs:
        if 'ar0' in xs:
            dd = d.dropna(subset=['ar0'])
            dmm = dd[[dep] + list(set(xs))].groupby(dd.ym).transform(lambda s: s - s.mean())
            y, X, g = dmm[dep].values, dmm[xs].values, dd.ym.values
        else:
            y, X, g = dm[dep].values, dm[xs].values, d.ym.values
        beta, se = cluster_ols(y, X, g)
        out.append((name, len(y), {x: (b, s) for x, b, s in zip(xs, beta, se)}))
    return out


# ── 主流程 ─────────────────────────────────────────────────────────────────────
def build(st_since: date, sources: list | None, min_history: int, research: bool = False, bench: str = '0050') -> dict:
    ids = universe(research)
    rev = load_revenue(ids)
    sur = surprises(rev, min_history)
    stocks = sorted(rev.stock_id.unique())
    px = load_prices(stocks + [BENCH], st_since - timedelta(days=200))
    wide = px.pivot(index='trade_date', columns='stock_id', values='px').astype(float)
    wide = wide.where(wide > 0)
    ret = np.log(wide).diff()
    ret = ret.where(ret.abs() < 0.5)
    if BENCH not in ret.columns:
        raise RuntimeError(f'缺 {BENCH} 價格')
    if bench == 'ew':
        # 等權基準：股票池內其他股票當日均值（排除自己）。0050 由台積電主導，跟中型股有共同漂移。
        cols = [c for c in ret.columns if c != BENCH]
        tot, cnt = ret[cols].sum(axis=1), ret[cols].notna().sum(axis=1)
        ar = pd.DataFrame({c: ret[c] - (tot - ret[c].fillna(0)) / (cnt - ret[c].notna().astype(int)).replace(0, np.nan)
                           for c in cols})
    else:
        ar = ret.sub(ret[BENCH], axis=0).drop(columns=[BENCH])
    open_days = list(ar.index)
    pos = {d: i for i, d in enumerate(open_days)}

    # 漲跌停鎖死旗標（依原始 close/high/low 與 change_rate）
    px = px.set_index(['stock_id', 'trade_date'])
    lock_up = (px.change_rate.astype(float) >= LIMIT_PCT) & (px.close_price == px.high_price)
    lock_dn = (px.change_rate.astype(float) <= -LIMIT_PCT) & (px.close_price == px.low_price)
    locked = (lock_up | lock_dn)
    vol = px.volume.astype(float).unstack(0)

    ev = sur.dropna(subset=['sue', 'announce_date']).copy()
    ev = ev[pd.to_datetime(ev.announce_date).dt.date >= st_since]
    if sources:
        ev = ev[ev.announce_source.isin(sources)]
    ev['t0'] = [event_day(r, open_days, pos) for r in ev.itertuples(index=False)]
    ev = ev.dropna(subset=['t0'])
    ev['i'] = ev.t0.map(pos)
    ev = ev.dropna(subset=['i'])
    ev['i'] = ev.i.astype(int)
    ev = ev[(ev.i >= PRE) & (ev.i + POST < len(open_days))]

    # 每檔自己的無事件日 |AR| 基準（對齊檢查用：不同來源涵蓋的股票不同，跨組比 |AR| 要先除以自身基準）
    ev_days_all = set()
    for e in ev.itertuples(index=False):
        for k in (-1, 0, 1):
            if 0 <= e.i + k < len(open_days):
                ev_days_all.add((e.stock_id, open_days[e.i + k]))
    base_stock = {}
    for c in ar.columns:
        s = ar[c].dropna()
        s = s[s.index >= st_since]
        v = [abs(x) for d, x in s.items() if (c, d) not in ev_days_all]
        base_stock[c] = float(np.mean(v)) if v else np.nan

    recs = []
    for e in ev.itertuples(index=False):
        if e.stock_id not in ar.columns:
            continue
        col = ar[e.stock_id].values
        seg = col[e.i - PRE:e.i + POST + 1]
        if np.isnan(seg[:PRE + 21]).any():        # 事件前與 [0,20] 必須完整；更長視窗允許缺
            continue
        r = {'stock_id': e.stock_id, 'revenue_month': e.revenue_month, 't0': e.t0, 'i': e.i,
             'src': e.announce_source, 'timed': pd.notna(e.announce_ts),
             'after_close': (pd.Timestamp(e.announce_ts).time() >= CLOSE_TW) if pd.notna(e.announce_ts) else None,
             'sue': e.sue, 'surprise': e.surprise, 'yoy': e.yoy, 'mom_sa': e.mom_sa,
             'pre_car': seg[:PRE].sum(), 'ar0': seg[PRE], 'abs_ar0': abs(seg[PRE]),
             'ar_m1': seg[PRE - 1], 'ar_p1': seg[PRE + 1], 'base_stock': base_stock.get(e.stock_id, np.nan)}
        for h in HORIZONS:
            s = seg[PRE + 1:PRE + 1 + h]
            r[f'car_1_{h}'] = np.nan if np.isnan(s).any() else s.sum()
        r['car_0_1'] = seg[PRE:PRE + 2].sum()
        # 動能與成交量控制
        r['mom60'] = np.nansum(ret[e.stock_id].values[max(0, e.i - 70):e.i - PRE])
        v = vol[e.stock_id]
        base = v.iloc[max(0, e.i - 30):e.i - PRE].mean()
        r['abn_vol'] = float(np.log(v.iloc[e.i] / base)) if base and base > 0 and v.iloc[e.i] > 0 else np.nan
        d0, d1 = open_days[e.i], open_days[e.i + 1]
        r['locked'] = bool(locked.get((e.stock_id, d0), False) or locked.get((e.stock_id, d1), False))
        recs.append(r)
    st_all = pd.DataFrame(recs)
    if st_all.empty:
        raise RuntimeError('沒有可用事件——先跑 backfill_revenue.py 與 backfill_revenue_dates.py --all')
    st_all['precise'] = st_all.src != 'estimated'
    st_all['q_all'] = pd.qcut(st_all.sue.rank(method='first'), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    st = st_all[st_all.precise].copy()                 # 主結論：只用有來源的公布日
    if len(st) < 25:
        raise RuntimeError(f'有來源的公布日事件只有 {len(st)} 個，先跑 backfill_revenue_dates.py --all')
    st['q'] = pd.qcut(st.sue.rank(method='first'), 5, labels=[1, 2, 3, 4, 5]).astype(int)

    # 無事件日 |AR| 基準（事件 [-1, +1] 以外）
    ev_days = set()
    for r in st.itertuples(index=False):
        for k in (-1, 0, 1):
            ev_days.add((r.stock_id, open_days[r.i + k]))
    vals = []
    for c in ar.columns:
        s = ar[c].dropna()
        s = s[s.index >= st_since]
        vals += [abs(v) for d, v in s.items() if (c, d) not in ev_days]
    base_abs = float(np.mean(vals)) if vals else float('nan')

    ct = {}
    for h in (5, 10, 20):
        ct[h] = calendar_time_t(ar, st, h, 5, 1)
    ct_unlocked = calendar_time_t(ar, st[~st.locked], 20, 5, 1)
    st_full = st_all.assign(q=st_all.q_all)
    ct_all = calendar_time_t(ar, st_full, 20, 5, 1)
    return {'st': st, 'st_all': st_full, 'base_abs': base_abs, 'ct': ct, 'ct_unlocked': ct_unlocked,
            'ct_all': ct_all, 'n_rev_rows': len(rev), 'n_sur': int(sur.sue.notna().sum()),
            'n_dated': int(sur.announce_date.notna().sum()), 'stocks': stocks}


def fmt_pct(x) -> str:
    return '–' if pd.isna(x) else f'{x * 100:+.2f}%'


def quintile_table(st: pd.DataFrame, title: str) -> list:
    out = [f'### {title}', '',
           '| 五分組 | n | SUE 均值 | CAR[−10,−1] | AR₀ | t(AR₀) | CAR[1,5] | CAR[1,10] | CAR[1,20] | t(CAR[1,20]) | CAR[1,60] |',
           '|--------|---|---------|-------------|-----|--------|----------|-----------|-----------|--------------|-----------|']
    for q, g in st.groupby('q'):
        out.append(f'| Q{q}{"（最負）" if q == 1 else "（最正）" if q == 5 else ""} | {len(g):,} | {g.sue.mean():+.2f} | '
                   f'{fmt_pct(g.pre_car.mean())} | {fmt_pct(g.ar0.mean())} | {tstat(g.ar0):+.1f} | '
                   f'{fmt_pct(g.car_1_5.mean())} | {fmt_pct(g.car_1_10.mean())} | {fmt_pct(g.car_1_20.mean())} | '
                   f'{tstat(g.car_1_20):+.1f} | {fmt_pct(g.car_1_60.mean())} |')
    q5, q1 = st[st.q == 5], st[st.q == 1]
    sp = {c: (q5[c].mean() - q1[c].mean()) for c in ('pre_car', 'ar0', 'car_1_5', 'car_1_10', 'car_1_20', 'car_1_60')}
    # Q5−Q1 的事件時間 t：兩獨立樣本 Welch
    def welch(a, b):
        a, b = a.dropna(), b.dropna()
        se = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
        return (a.mean() - b.mean()) / se if se > 0 else float('nan')
    out.append(f'| **Q5 − Q1** | | | {fmt_pct(sp["pre_car"])} | {fmt_pct(sp["ar0"])} | {welch(q5.ar0, q1.ar0):+.1f} | '
               f'{fmt_pct(sp["car_1_5"])} | {fmt_pct(sp["car_1_10"])} | {fmt_pct(sp["car_1_20"])} | '
               f'{welch(q5.car_1_20, q1.car_1_20):+.1f} | {fmt_pct(sp["car_1_60"])} |')
    means = st.groupby('q').car_1_20.mean()
    rho = pd.Series(means.values).corr(pd.Series(range(1, 6)), method='spearman')
    mono = '單調' if abs(rho) == 1 else f'不完全單調（Spearman {rho:+.1f}）'
    out += ['', f'五分組 CAR[1,20] 由 Q1 到 Q5：{mono}。', '']
    return out


def report(res: dict, since: date, sources: list | None) -> str:
    st, base = res['st'], res['base_abs']
    n_timed = int(st.timed.sum())
    after = st.loc[st.timed, 'after_close'].mean() if n_timed else float('nan')
    src_counts = st.src.value_counts()
    L = ['# 月營收事件研究（Iteration 39，新聞訊號研究方案階段 1）', '',
         f'產出時間 {datetime.now():%Y-%m-%d %H:%M}。事件 **{len(st):,}** 個（{st.stock_id.nunique()} 檔 × 月），'
         f'公布日 ≥ {since}，視窗 [−{PRE}, +{POST}] 交易日，AR = 個股 − '
         + ('股票池等權均值（排除自己）' if res.get('bench') == 'ew' else BENCH) + '（log 報酬）。'
         + ('股票池 = 追蹤股 + 研究股（research_daily_prices，未還原權息）。' if res.get('research') else ''),
         f'營收列 {res["n_rev_rows"]:,}、算得出 SUE {res["n_sur"]:,}、有公布日 {res["n_dated"]:,}。'
         f'無事件日 |AR| 基準 = **{base * 100:.2f}%**。', '',
         '## N0 時間戳', '',
         '| 來源 | n | 精度 |', '|------|---|------|']
    prec = {'mops_item': '秒（MOPS 公告）', 'cnyes_item': '秒（鉅亨營收速報）', 'news_item': '秒（媒體標題最早一則）',
            'finmind': '日（FinMind create_time）', 'cnyes_list': '日（鉅亨每日一覽，清單日 − 1）'}
    yoy_med = st.groupby('src').yoy.median()
    for s, n in src_counts.items():
        L.append(f'| {s} | {n:,} | {prec.get(s, "?")} | {np.expm1(yoy_med.get(s, np.nan)) * 100:+.0f}% |')
    L[-len(src_counts) - 2] = '| 來源 | n | 精度 | 事件 YoY 中位數 |'
    L[-len(src_counts) - 1] = '|------|---|------|---------------|'
    if src_counts.get('cnyes_item', 0) / len(st) > 0.5:
        L += ['', '**選樣警告**：鉅亨「營收速報」個股快訊只寫年增率高的公司（6,174 則標題全部含「年增」、0 則「年減」），'
              '這個來源的事件 YoY 中位數遠高於其他來源。以它為主的樣本是「被媒體報導的強勁營收月」，'
              '不是全部月營收；結論只適用於這個條件。']
    L += ['', f'有時間戳的 {n_timed:,} 個事件中，**{after:.0%} 在 13:30 收盤後公布**；只有日期的事件因此一律歸下一交易日為 t=0。'
          if n_timed else '本次沒有帶時間戳的事件。', '']
    # 對齊檢查：反應日應該落在 t=0；若某組 t=−1 的 |AR| 也高，代表那組的日期晚了一天
    sa = res['st_all'].copy()
    sa['grp'] = sa.src.map(lambda s: f'{s}（{"秒" if s in ("mops_item", "cnyes_item", "news_item") else "日"}）')
    L += ['對齊檢查——各精度組在 t=−1 / 0 / +1 的 |AR| ÷ 該股自身無事件日 |AR|（反應日應集中在 t=0；'
          '若 t=−1 也高，代表日期晚了一天；若 t=+1 才高，代表早了一天）：', '',
          '| 精度組 | n | t=−1 | t=0 | t=+1 |', '|--------|---|------|-----|------|']
    for g, d in sa.groupby('grp'):
        L.append(f'| {g} | {len(d):,} | ×{(d.ar_m1.abs() / d.base_stock).mean():.2f} | '
                 f'×{(d.abs_ar0 / d.base_stock).mean():.2f} | ×{(d.ar_p1.abs() / d.base_stock).mean():.2f} |')
    L.append('')

    L += ['## N1 公布後有沒有漂移（全部事件）', '']
    L += quintile_table(st, '按 SUE 五分組（全樣本切）')
    L += ['### Q5 − Q1 日曆時間投資組合（處理同日叢集）', '',
          '| 持有期 | 期間報酬（Q5−Q1） | t | 交易日數 |', '|--------|------------------|---|---------|']
    for h, (r, t, n) in res['ct'].items():
        L.append(f'| [1,{h}] | {fmt_pct(r)} | {t:+.1f} | {n} |')
    L += ['', '事件時間 t 值假設事件獨立；月營收在每月 1~10 日叢集，日曆時間 t 值才是可信的那一個。', '']

    L += ['## N3 漲跌停', '',
          f'{int(st.locked.sum())} 個事件在 t=0 或 t=+1 鎖漲停或跌停（|漲跌幅| ≥ {LIMIT_PCT}% 且收在最高／最低），'
          f'占 {st.locked.mean():.1%}。剔除後：', '']
    L += quintile_table(st[~st.locked], '按 SUE 五分組（剔除鎖死）')
    r, t, n = res['ct_unlocked']
    L += [f'剔除鎖死後 Q5−Q1 日曆時間 [1,20]：{fmt_pct(r)}，t {t:+.1f}（{n} 個交易日）。', '']

    L += ['## 波動：|AR₀| 相對無事件日', '',
          '| 分組 | n | \\|AR₀\\| | 相對基準 |', '|------|---|--------|---------|']
    for name, g in [('全部', st)] + [(f'Q{q}', g) for q, g in st.groupby('q')]:
        L.append(f'| {name} | {len(g):,} | {g.abs_ar0.mean() * 100:.2f}% | ×{g.abs_ar0.mean() / base:.2f} |')
    L.append('')

    L += ['## N2 增量檢定（月份固定效果、按月份叢集 SE）', '',
          '被解釋變數 CAR[1,20]。控制：事件前 CAR[−10,−1]、60 日動能（[−70,−11]）、異常成交量（t=0 量 ÷ 事件前 20 日均量，log）。', '',
          '| 設定 | n | 變數 | 係數 | SE | t |', '|------|---|------|------|----|---|']
    for name, n, coefs in incremental_regression(st):
        for x, (b, s) in coefs.items():
            L.append(f'| {name} | {n:,} | {x} | {b:+.4f} | {s:.4f} | {b / s if s > 0 else float("nan"):+.1f} |')
    L.append('')

    # 對照：surprise 分組 vs 單純 YoY 分組（方案文件：PEAD 的驅動力是 surprise 不是水準）
    st2 = st.copy()
    st2['q'] = pd.qcut(st2.yoy.rank(method='first'), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    L += ['## 對照：改用 YoY 水準分組', '']
    L += quintile_table(st2, '按 YoY 五分組（不是 surprise）')
    st3 = st.dropna(subset=['mom_sa']).copy()
    if len(st3) >= 25:
        st3['q'] = pd.qcut(st3.mom_sa.rank(method='first'), 5, labels=[1, 2, 3, 4, 5]).astype(int)
        L += ['## 對照：季節調整後月增（MoM − 去年同期 MoM）分組', '']
        L += quintile_table(st3, '按季節調整月增五分組')

    # 含估計公布日的完整樣本（只看樣本數變大後方向是否一致）
    sa = res['st_all']
    n_est = int((~sa.precise).sum())
    if n_est:
        L += ['## 補充：含估計公布日（來源 estimated）的完整樣本', '',
              f'另有 {n_est:,} 個事件的公布日是用該股習慣公布日估的；估錯一天會把反應日漏到事件前或漂移視窗，'
              '所以只看方向是否與主結論一致，不作為結論。', '']
        L += quintile_table(sa, f'按 SUE 五分組（全部 {len(sa):,} 個事件）')
        r, t, n = res['ct_all']
        L += [f'含估計事件的 Q5−Q1 日曆時間 [1,20]：{fmt_pct(r)}，t {t:+.1f}（{n} 個交易日）。', '']

    # 自動判讀
    q5, q1 = st[st.q == 5], st[st.q == 1]
    d20 = q5.car_1_20.mean() - q1.car_1_20.mean()
    ct20 = res['ct'][20]
    reg = {n: c for n, _, c in incremental_regression(st)}
    sue_t = None
    if 'SUE + 動能 + 成交量' in reg:
        b, s = reg['SUE + 動能 + 成交量']['sue']
        sue_t = b / s if s > 0 else float('nan')
    L += ['## 關卡判讀（程式自動）', '',
          f'- **N0**：{len(st):,} 個事件全部有可考的公布日；{n_timed / len(st):.0%} 精確到秒。'
          + ('' if n_timed == 0 else f' 收盤後公布占 {after:.0%}，「只有日期 → 下一交易日」的假設'
             + ('成立。' if after >= 0.85 else '**不夠穩**，只有日期的事件應另外分組檢查。')),
          f'- **N1**：Q5−Q1 的 CAR[1,20] = {fmt_pct(d20)}，日曆時間 t = {ct20[1]:+.1f}'
          + ('，**有可交易的漂移**。' if abs(ct20[1]) >= 2 and d20 > 0 else '，**漂移不顯著**。')
          + f' 當日 Q5−Q1 的 AR₀ = {fmt_pct(q5.ar0.mean() - q1.ar0.mean())}、全部事件 |AR₀| 是無事件日的 '
          f'×{st.abs_ar0.mean() / base:.2f}'
          + ('：公布日的反應不隨 surprise 分組改變，代表這個 surprise 定義（季節性隨機漫步＋趨勢）不是市場的預期基準，'
             '或月營收早被法說會指引與外資預估消化。' if abs(q5.ar0.mean() - q1.ar0.mean()) < 0.005 else
             '：公布日有反應，之後的漂移才是問題。'),
          (lambda c: f'- **反應日 → 漂移**：CAR[1,20] 對 AR₀ 的係數 {c[0]:+.2f}（t {c[0] / c[1]:+.1f}，月份固定效果）'
                     + ('，**公布日反應強的事件之後繼續同方向走**——這是 PEAD 的形狀，只是驅動它的不是我們定義的 surprise，'
                        '而是市場自己在公布日的判斷。' if abs(c[0] / c[1]) >= 2.5 else '，公布日反應不預測後續。'))(
              reg['AR₀ 單獨']['ar0']) if 'AR₀ 單獨' in reg else '',
          f'- **N2**：控制動能與成交量後 SUE 的 t = {sue_t:+.1f}'
          + ('，增量成立。' if sue_t is not None and abs(sue_t) >= 2 else '，**沒有增量**或樣本不足。') if sue_t is not None else '- **N2**：樣本不足，無法迴歸。',
          f'- **N3**：鎖漲跌停 {st.locked.mean():.1%}，剔除後 Q5−Q1 [1,20] 日曆時間 t = {res["ct_unlocked"][1]:+.1f}。',
          '', (f'- 股票池 {st.stock_id.nunique()} 檔、五分組每組約 {len(st) // 5} 個事件。'
               if res.get('research') else
               f'- 23 檔非 ETF 追蹤股是這份研究的硬限制：每月只有二十幾個事件，五分組每組約 {len(st) // 5} 個。'
               '結論的方向可信、幅度要用 --research 擴大股票池再確認。'), '']
    return '\n'.join(L)


def main():
    warnings.filterwarnings('ignore')
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', default='2023-09-01', help='公布日下限')
    ap.add_argument('--sources', default='', help='逗號分隔，只用這些 announce_source')
    ap.add_argument('--min-history', type=int, default=12, help='算 SUE 標準差至少要幾個月')
    ap.add_argument('--research', action='store_true', help='股票池加上 research_daily_prices 的研究股（research_universe.py）')
    ap.add_argument('--bench', default='0050', choices=['0050', 'ew'], help='基準：0050 或股票池等權均值')
    a = ap.parse_args()
    since = date.fromisoformat(a.since)
    sources = [s for s in a.sources.split(',') if s] or None
    res = build(since, sources, a.min_history, a.research, a.bench)
    res['bench'], res['research'] = a.bench, a.research
    md = report(res, since, sources)
    out = OUT.replace('.md', '_universe.md') if a.research else OUT
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(md)
    print(md)
    st = res['st']
    csv = out.replace('.md', '_events.csv')
    st.drop(columns=['i']).to_csv(csv, index=False, encoding='utf-8-sig')
    print(f'\n→ {os.path.abspath(OUT)}\n→ {os.path.abspath(csv)}')


if __name__ == '__main__':
    main()
