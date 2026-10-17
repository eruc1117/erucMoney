"""
月調倉選股訊號（Iteration 49，打敗大盤計畫階段 2）
────────────────────────────────────────────────
每月 11 日（或之後第一個交易日）收盤後算一次：股票池 → 排除 → 訊號 → 前 20 名等權。
只讀 market_daily_prices（全市場，Iteration 48）、stock_revenue_announce、0050（stock_daily_prices）。

點時規則（N0，不能破）：訊號日 d 的所有計算只能用 trade_date ≤ d 的價格、revenue_month ≤ d 所在月的營收
（台股月營收依法 10 日前公布，11 日算訊號時當月那一期已全部可知），公告日反應只能用反應日 ≤ d 的事件。

三種訊號（每一種都是一次嘗試，實驗日誌 N 加 1）：
    sue   標準化營收驚喜：與 revenue_event_study.surprises 同一個定義（YoY 減前三期 YoY 均值，除以 24 個月標準差）。
          全市場都算得出，不需要公告日。第 39 次迭代在 185 檔上不顯著，全市場是第一次測。
    ar0   公告日異常報酬：反應日個股 log 報酬減 0050。只有公告日精確的月份有（mops/cnyes/news/finmind/cnyes_list 來源），
          2024-03 以前幾乎沒有，所以能測的期間短。第 39 次迭代：AR₀ 對後 20 日 CAR 係數 +0.41（t 4.0）。
    win   公告窗口異常報酬：當月 1 日到訊號日的累積異常報酬。沒有精確公告日時的 AR₀ 近似——市場對本月營收的反應
          幾乎都落在這個窗口裡，代價是混進了窗口內的其他消息。

股票池（訊號日）：market_universe 當天在市、當天有收盤價、過去 60 個交易日平均成交金額前 universe_n 名；
排除過去 20 個交易日漲停次數在前 excl_limit_pct 的（MAX 效果）；台積電不參與排名（可選固定權重）。
"""

import logging
from datetime import date, datetime, time as dtime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from db.connection import get_conn

logger = logging.getLogger(__name__)

BENCH = '0050'
TSMC = '2330'
PRECISE_SOURCES = ('mops_item', 'cnyes_item', 'news_item', 'finmind', 'cnyes_list')
SUE_MIN_HISTORY = 12
LIMIT_UP = 0.095
CLOSE_TIME = dtime(13, 30)


# ── 載入 ──────────────────────────────────────────────────────────────────────

def load_prices(start: date, end: date, extra_days: int = 130) -> pd.DataFrame:
    """股票池日線（start 往前多拉 extra_days 給 60 日流動性與 20 日漲停統計）+ 0050。"""
    since = start - timedelta(days=extra_days)
    sql = """
        SELECT stock_id, trade_date, open_price, high_price, low_price, close_price, adj_close, turnover_value
          FROM market_daily_prices WHERE trade_date BETWEEN %s AND %s AND adj_close > 0
        UNION ALL
        SELECT stock_id, trade_date, open_price, high_price, low_price, close_price, adj_close, turnover_value
          FROM stock_daily_prices WHERE stock_id = %s AND trade_date BETWEEN %s AND %s AND adj_close > 0"""
    with get_conn() as conn:
        df = pd.read_sql(sql, conn, params=(since, end, BENCH, since, end))
    for c in ('open_price', 'high_price', 'low_price', 'close_price', 'adj_close', 'turnover_value'):
        df[c] = df[c].astype(float)
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    return df


def load_universe_meta() -> pd.DataFrame:
    with get_conn() as conn:
        m = pd.read_sql("SELECT stock_id, listing_date, delisted_date, industry_type, market_type FROM market_universe", conn)
    m['listing_date'] = pd.to_datetime(m['listing_date'])
    m['delisted_date'] = pd.to_datetime(m['delisted_date'])
    return m.set_index('stock_id')


def load_revenue(start: date) -> pd.DataFrame:
    """revenue_month ≥ start 前 40 個月（SUE 要 24 個月標準差 + 12 個月 YoY 基期）。"""
    since = date(start.year - 4, start.month, 1)
    with get_conn() as conn:
        r = pd.read_sql("""SELECT stock_id, revenue_month, revenue, announce_date, announce_ts, announce_source
                             FROM stock_revenue_announce WHERE revenue_month >= %s AND revenue IS NOT NULL""",
                        conn, params=(since,))
    r['revenue_month'] = pd.to_datetime(r['revenue_month'])
    r['announce_date'] = pd.to_datetime(r['announce_date'])
    r['announce_ts'] = pd.to_datetime(r['announce_ts'])
    r['revenue'] = r['revenue'].astype(float)
    return r


# ── 營收驚喜（與 revenue_event_study.surprises 同定義）────────────────────────

def surprises(rev: pd.DataFrame, min_history: int = SUE_MIN_HISTORY) -> pd.DataFrame:
    out = []
    for sid, g in rev.groupby('stock_id'):
        s = g.set_index('revenue_month')['revenue'].astype(float)
        s = s[~s.index.duplicated()].sort_index()
        s = s.where(s > 0)
        if len(s) < 14:
            continue
        idx = pd.date_range(s.index.min(), s.index.max(), freq='MS')
        s = s.reindex(idx)
        lg = np.log(s)
        yoy = lg - lg.shift(12)
        trend = pd.concat([yoy.shift(k) for k in (1, 2, 3)], axis=1).mean(axis=1, skipna=False)
        sur = yoy - trend
        sd = sur.shift(1).rolling(24, min_periods=min_history).std()
        df = pd.DataFrame({'stock_id': sid, 'yoy': yoy, 'surprise': sur, 'sue': sur / sd})
        df.index.name = 'revenue_month'
        out.append(df.reset_index())
    if not out:
        return pd.DataFrame(columns=['stock_id', 'revenue_month', 'yoy', 'surprise', 'sue', 'announce_date', 'announce_ts', 'announce_source'])
    res = pd.concat(out, ignore_index=True)
    return res.merge(rev[['stock_id', 'revenue_month', 'announce_date', 'announce_ts', 'announce_source']],
                     on=['stock_id', 'revenue_month'], how='left')


def reaction_day(announce_date, announce_ts, open_days: np.ndarray):
    """公告的市場反應日：13:30 前公告 → 當天（非交易日則下一個）；之後或只有日期（94% 盤後公布）→ 下一個交易日。"""
    if pd.isna(announce_date):
        return None
    if pd.notna(announce_ts):
        ts = pd.Timestamp(announce_ts)
        base, same_day = ts.normalize(), ts.time() <= CLOSE_TIME
    else:
        base, same_day = pd.Timestamp(announce_date).normalize(), False
    i = np.searchsorted(open_days, np.datetime64(base), side='left' if same_day else 'right')
    return pd.Timestamp(open_days[i]) if i < len(open_days) else None


# ── 寬表 ──────────────────────────────────────────────────────────────────────

class Market:
    """由長表建一次寬表（index = 交易日，columns = 股票），供訊號與回測共用。"""

    def __init__(self, prices: pd.DataFrame, meta: pd.DataFrame):
        p = prices.drop_duplicates(['stock_id', 'trade_date'])
        piv = lambda c: p.pivot(index='trade_date', columns='stock_id', values=c).sort_index()
        self.adj = piv('adj_close')
        self.close = piv('close_price')
        self.open = piv('open_price')
        self.high = piv('high_price')
        self.low = piv('low_price')
        self.turnover = piv('turnover_value')
        self.days = self.adj.index.values            # datetime64[ns]，升冪
        self.meta = meta
        factor = self.adj / self.close
        self.adj_open = self.open * factor
        lr = np.log(self.adj).diff()
        self.ar = lr.sub(lr[BENCH], axis=0) if BENCH in lr.columns else lr
        # 日內 log 報酬（收盤 ÷ 開盤，同一天不用還原）減 0050 同項：給 `imom`（Iteration 69）。開盤 ≤ 0 的那天當缺值
        li = np.log(self.close / self.open.where(self.open > 0))
        self.ar_intra = li.sub(li[BENCH], axis=0) if BENCH in li.columns else li
        self.ar_over = self.ar - self.ar_intra        # 隔夜異常報酬 = 總異常報酬 − 日內（還原收盤算的總報酬含除息調整）
        self.liq = self.turnover.rolling(60, min_periods=40).mean()
        up = (self.close / self.close.shift(1) - 1 >= LIMIT_UP)
        self.limit_up_20 = up.rolling(20, min_periods=1).sum()
        prev = self.close.shift(1)
        # 一字鎖死：最高 = 最低，且相對前收 ≥ 9.5%（漲停或跌停都算）→ 開盤單視為未成交
        self.locked = (self.high == self.low) & ((self.open / prev - 1).abs() >= LIMIT_UP)

    def active_on(self, d: pd.Timestamp) -> pd.Index:
        m = self.meta
        ok = ((m['listing_date'].isna()) | (m['listing_date'] <= d)) & ((m['delisted_date'].isna()) | (m['delisted_date'] > d))
        return m.index[ok].intersection(self.adj.columns)

    def next_day(self, d: pd.Timestamp) -> Optional[pd.Timestamp]:
        i = np.searchsorted(self.days, np.datetime64(d), side='right')
        return pd.Timestamp(self.days[i]) if i < len(self.days) else None

    def first_day_on_or_after(self, d: date) -> Optional[pd.Timestamp]:
        i = np.searchsorted(self.days, np.datetime64(pd.Timestamp(d)), side='left')
        return pd.Timestamp(self.days[i]) if i < len(self.days) else None


def rebalance_schedule(mkt: Market, start: date, end: date, day: int = 11) -> list[tuple]:
    """[(訊號日, 成交日)]：每月 day 日或之後第一個交易日收盤算訊號，次一交易日開盤成交；成交日要在 end 之內。"""
    out = []
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        s = mkt.first_day_on_or_after(date(y, m, day))
        if s is None or s.date() > end or s.month != m:
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
            continue
        e = mkt.next_day(s)
        if e is None or e.date() > end:
            break
        out.append((s, e))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


# ── 股票池與訊號 ──────────────────────────────────────────────────────────────

def eligible(mkt: Market, d: pd.Timestamp, universe_n: int = 300, excl_limit_pct: float = 0.10) -> pd.Index:
    """訊號日的候選：在市、當天有價、流動性前 universe_n，排除漲停次數前 excl_limit_pct；不含 0050 與台積電。"""
    ids = mkt.active_on(d).difference([BENCH, TSMC])
    has = mkt.adj.loc[d, ids].notna()
    ids = ids[has.values]
    liq = mkt.liq.loc[d, ids].dropna().sort_values(ascending=False)
    ids = liq.index[:universe_n]
    if excl_limit_pct > 0 and len(ids):
        lu = mkt.limit_up_20.loc[d, ids].fillna(0)
        k = int(round(len(ids) * excl_limit_pct))
        if k > 0:
            worst = lu.sort_values(ascending=False)
            # 只排除真的有漲停紀錄的（0 次的不算「前 10%」）
            drop = worst.index[:k][worst.iloc[:k].values > 0]
            ids = ids.difference(drop)
    return pd.Index(ids)


def signal_sue(sur: pd.DataFrame, d: pd.Timestamp) -> pd.Series:
    """訊號日所在月的 revenue_month（= 當月 1 日，即上月營收、10 日前已公布）那一期的 SUE。"""
    rm = pd.Timestamp(year=d.year, month=d.month, day=1)
    x = sur[(sur['revenue_month'] == rm)].dropna(subset=['sue'])
    return x.set_index('stock_id')['sue']


def signal_win(mkt: Market, d: pd.Timestamp, min_days: int = 3) -> pd.Series:
    """當月 1 日到訊號日（含）的累積異常報酬（log，減 0050）。"""
    start = pd.Timestamp(year=d.year, month=d.month, day=1)
    seg = mkt.ar.loc[start:d]
    if len(seg) < min_days:
        return pd.Series(dtype=float)
    return seg.sum(min_count=min_days).dropna()


def signal_ar0(sur: pd.DataFrame, mkt: Market, d: pd.Timestamp) -> pd.Series:
    """公告日精確的事件：反應日 ≤ d 的異常報酬。"""
    rm = pd.Timestamp(year=d.year, month=d.month, day=1)
    x = sur[(sur['revenue_month'] == rm) & (sur['announce_source'].isin(PRECISE_SOURCES))]
    out = {}
    for row in x.itertuples(index=False):
        t0 = reaction_day(row.announce_date, row.announce_ts, mkt.days)
        if t0 is None or t0 > d or row.stock_id not in mkt.ar.columns:
            continue
        v = mkt.ar.at[t0, row.stock_id]
        if pd.notna(v):
            out[row.stock_id] = float(v)
    return pd.Series(out, dtype=float)


def signal_mom(mkt: Market, d: pd.Timestamp, long_days: int = 252, skip_days: int = 21) -> pd.Series:
    """12-1 動能：d 往前 252 個交易日到 21 個交易日的累積異常報酬（跳過最近一個月的反轉）。"""
    i = int(np.searchsorted(mkt.days, np.datetime64(d), side='right')) - 1
    if i - long_days < 0:
        return pd.Series(dtype=float)
    seg = mkt.ar.iloc[i - long_days + 1:i - skip_days + 1]
    return seg.sum(min_count=int(len(seg) * 0.8)).dropna()


def signal_win3(mkt: Market, d: pd.Timestamp) -> pd.Series:
    """最近三個公告窗口（本月、上月、上上月的 1 日到 11 日）的累積異常報酬：平滑版 win。"""
    total = None
    for k in range(3):
        y, m = d.year, d.month - k
        while m <= 0:
            y, m = y - 1, m + 12
        start = pd.Timestamp(year=y, month=m, day=1)
        end = min(d, pd.Timestamp(year=y, month=m, day=11)) if k else d
        seg = mkt.ar.loc[start:end]
        s = seg.sum(min_count=3)
        total = s if total is None else total.add(s, fill_value=np.nan)
    return total.dropna() if total is not None else pd.Series(dtype=float)


# ── 第二批：不同假設的訊號家族（Iteration 53）──────────────────────────────

def _window(mkt: Market, d: pd.Timestamp, n: int):
    i = int(np.searchsorted(mkt.days, np.datetime64(d), side='right'))
    return (None if i < n + 1 else slice(i - n, i)), i


def signal_lowvol(mkt: Market, d: pd.Timestamp, n: int = 60) -> pd.Series:
    """低波動：過去 60 日 log 報酬標準差取負（低波動異象：波動低的股票風險調整後報酬較高）。"""
    sl, _ = _window(mkt, d, n + 1)
    if sl is None:
        return pd.Series(dtype=float)
    lr = np.log(mkt.adj.iloc[sl]).diff().iloc[1:]
    sd = lr.std().where(lr.count() >= int(n * 0.8))
    return (-sd).dropna()


def signal_hi52(mkt: Market, d: pd.Timestamp, n: int = 252) -> pd.Series:
    """52 週高點接近度：收盤 ÷ 過去 252 日最高收盤（George & Hwang 2004：靠近高點的股票之後表現較好）。"""
    sl, _ = _window(mkt, d, n)
    if sl is None:
        return pd.Series(dtype=float)
    seg = mkt.adj.iloc[sl]
    hi = seg.max().where(seg.count() >= int(n * 0.8))
    return (seg.iloc[-1] / hi).dropna()


def signal_rev1m(mkt: Market, d: pd.Timestamp, n: int = 21) -> pd.Series:
    """1 個月反轉：過去 21 日累積異常報酬取負（短期反轉；台股文獻說反轉比動能常見）。"""
    sl, _ = _window(mkt, d, n + 1)
    if sl is None:
        return pd.Series(dtype=float)
    seg = mkt.ar.iloc[sl].iloc[1:]
    return (-seg.sum(min_count=int(n * 0.8))).dropna()


def signal_volchg(mkt: Market, d: pd.Timestamp, short: int = 20, long: int = 120) -> pd.Series:
    """異常成交量：近 20 日平均成交金額 ÷ 近 120 日平均（注意力／資金流入）。"""
    sl, _ = _window(mkt, d, long)
    if sl is None:
        return pd.Series(dtype=float)
    seg = mkt.turnover.iloc[sl]
    recent = seg.iloc[-short:]
    ratio = recent.mean().where(recent.count() >= int(short * 0.8)) / seg.mean().where(seg.count() >= int(long * 0.8))
    return np.log(ratio.replace(0, np.nan)).dropna()


def _rev_rows(sur: pd.DataFrame, d: pd.Timestamp) -> pd.DataFrame:
    rm = pd.Timestamp(year=d.year, month=d.month, day=1)
    return sur[sur['revenue_month'] <= rm]


def signal_rev_accel(sur: pd.DataFrame, d: pd.Timestamp) -> pd.Series:
    """營收加速：最新 YoY（log）減三期前的 YoY——基本面動能的二階項。"""
    rows = _rev_rows(sur, d)
    out = {}
    for sid, g in rows.groupby('stock_id'):
        g = g.sort_values('revenue_month')
        rm = pd.Timestamp(year=d.year, month=d.month, day=1)
        if g['revenue_month'].iloc[-1] != rm or len(g) < 4:
            continue
        y = g['yoy'].values
        if np.isnan(y[-1]) or np.isnan(y[-4]):
            continue
        out[sid] = float(y[-1] - y[-4])
    return pd.Series(out, dtype=float)


def signal_rev_streak(sur: pd.DataFrame, d: pd.Timestamp, cap: int = 24) -> pd.Series:
    """營收連續成長：最近連續幾個月 YoY > 0（最多 24），品質／穩定度的代理。"""
    rows = _rev_rows(sur, d)
    out = {}
    rm = pd.Timestamp(year=d.year, month=d.month, day=1)
    for sid, g in rows.groupby('stock_id'):
        g = g.sort_values('revenue_month')
        if g['revenue_month'].iloc[-1] != rm:
            continue
        n = 0
        for v in g['yoy'].values[::-1]:
            if np.isnan(v) or v <= 0 or n >= cap:
                break
            n += 1
        out[sid] = float(n)
    return pd.Series(out, dtype=float)


# ── 第三批：文獻假設（Iteration 66，見 AI/Doc/Papers.md）────────────────────────

def signal_resmom(mkt: Market, d: pd.Timestamp, long_days: int = 252, skip_days: int = 21) -> pd.Series:
    """
    殘差動能（Blitz, Huij & Martens 2011）：先把每檔過去 252 日的 log 報酬對 0050 做 OLS（α、β），
    拿殘差在 12-1 窗口（跳過最近 21 日）的累積值除以殘差標準差當訊號。
    和 `mom`（減 0050 的異常報酬，等於硬設 β = 1）的差別：β 高的股票不會只因為大盤漲就排前面，
    文獻說這樣能把動能的因子暴露（這裡是對 0050 的追蹤誤差）壓低、風險調整後報酬提高。只用 d 以前的價格。

    β 用**過原點**的迴歸（β = Σ r·r_b ÷ Σ r_b²），不帶截距：文獻是用 36 個月估 β、再看最近 12 個月的殘差，
    我們只有 252 日的窗口，若在同一窗口帶截距，殘差總和恆為 0，「前 231 日殘差和」就等於「最近 21 日殘差的負值」，
    訊號會變成一個月反轉而不是動能（#71、#72、#76 就是這個錯的版本，tests 抓到後改的，見 Iteration 66）。
    """
    i = int(np.searchsorted(mkt.days, np.datetime64(d), side='right')) - 1
    if i - long_days < 0 or BENCH not in mkt.adj.columns:
        return pd.Series(dtype=float)
    lr = np.log(mkt.adj.iloc[i - long_days:i + 1]).diff().iloc[1:]
    rb = lr[BENCH]
    r = lr.drop(columns=[BENCH])
    m = r.notna() & rb.notna().values[:, None]
    n = m.sum()
    rb_mat = pd.DataFrame(np.where(m, rb.values[:, None], np.nan), index=r.index, columns=r.columns)
    r = r.where(m)
    beta = (r * rb_mat).sum() / (rb_mat ** 2).sum().replace(0, np.nan)
    e = r - beta * rb_mat
    form = e.iloc[:len(e) - skip_days]
    sd = form.std()
    sig = form.sum(min_count=int(len(form) * 0.8)) / sd.replace(0, np.nan)
    return sig.where(n >= int(long_days * 0.8)).dropna()


def signal_rev_yoy3(sur: pd.DataFrame, d: pd.Timestamp) -> pd.Series:
    """
    營收動能（Hung, Lu & Yang 2025；Chen, Chen, Hsin & Lee 2014）：最近三期 YoY（log）的平均。
    文獻用的是「營收年增率的水準與持續性」，不是驚喜（`sue`）也不是二階差（`rev_accel`）；三期平均是為了
    壓掉單月的噪音。只用 revenue_month ≤ 訊號日所在月的資料（當月那一期 10 日前已公布）。
    """
    rows = _rev_rows(sur, d)
    rm = pd.Timestamp(year=d.year, month=d.month, day=1)
    out = {}
    for sid, g in rows.groupby('stock_id'):
        g = g.sort_values('revenue_month')
        if g['revenue_month'].iloc[-1] != rm or len(g) < 3:
            continue
        y = g['yoy'].values[-3:]
        if np.isnan(y).any():
            continue
        out[sid] = float(y.mean())
    return pd.Series(out, dtype=float)


def signal_momrev(mkt: Market, sur: pd.DataFrame, d: pd.Timestamp) -> pd.Series:
    """
    以營收為條件的動能（Novy-Marx 2015：價格動能來自對基本面驚喜的反應不足；Iteration 68）：
    `mom` 的值，但只給當月 SUE > 0 的股票；SUE ≤ 0 或沒有 SUE 的不給值（組合裡會因此被排除）。
    不是把營收和動能相加（那是 rev_accel+mom），是用營收當篩選條件。
    """
    m = signal_mom(mkt, d)
    s = signal_sue(sur, d)
    keep = s[s > 0].index
    return m.reindex(m.index.intersection(keep)).dropna()


# ── 第四批：文獻第二批（Iteration 69）────────────────────────────────────────

def _mom_window(mkt: Market, d: pd.Timestamp, long_days: int, skip_days: int) -> Optional[slice]:
    """`mom` 用的形成期：d 往前 long_days 個交易日到 skip_days 個交易日（含 d 當天往前數）；歷史不足回 None。"""
    i = int(np.searchsorted(mkt.days, np.datetime64(d), side='right')) - 1
    if i - long_days < 0:
        return None
    return slice(i - long_days + 1, i - skip_days + 1)


def signal_cont(mkt: Market, d: pd.Timestamp, long_days: int = 252, skip_days: int = 21) -> pd.Series:
    """
    資訊連續性（Da, Gurun & Warachka 2014「Frog in the Pan」）：`mom` 同一個 12-1 窗口內，
    異常報酬 > 0 的天數比例減 < 0 的天數比例。文獻的 ID = sign(PRET) × (%neg − %pos)，對贏家而言這裡的值 = −ID；
    排名用、不乘 sign——和 `mom` 相加後，靠很多小漲累積的贏家排前面、靠幾次跳空的排後面。
    有值的天數要達窗口的 80%，和 `mom` 的 min_count 一致。
    """
    sl = _mom_window(mkt, d, long_days, skip_days)
    if sl is None:
        return pd.Series(dtype=float)
    seg = mkt.ar.iloc[sl]
    n = seg.count()
    frac = ((seg > 0).sum() - (seg < 0).sum()) / n.replace(0, np.nan)
    return frac.where(n >= int(len(seg) * 0.8)).dropna()


def signal_imom(mkt: Market, d: pd.Timestamp, long_days: int = 252, skip_days: int = 21) -> pd.Series:
    """
    日內動能（Ho, Hsiao, Lo & Yang 2023，台灣；Lou, Polk & Skouras 2019）：12-1 窗口內日內異常報酬
    （log(收盤 ÷ 開盤) 減 0050 同項）的累積。把 `mom` 的隔夜那一半拿掉；台灣文獻說日內動能為正且穩定、隔夜動能為負。
    """
    sl = _mom_window(mkt, d, long_days, skip_days)
    if sl is None:
        return pd.Series(dtype=float)
    seg = mkt.ar_intra.iloc[sl]
    return seg.sum(min_count=int(len(seg) * 0.8)).dropna()


def signal_mom127(mkt: Market, d: pd.Timestamp) -> pd.Series:
    """中期動能 12-7（Novy-Marx 2012）：形成期前 252 到 126 個交易日的累積異常報酬，跳過最近六個月。"""
    return signal_mom(mkt, d, long_days=252, skip_days=126)


# ── 第五批（Iteration 70）──────────────────────────────────────────────────

def signal_ovn1m(mkt: Market, d: pd.Timestamp, n: int = 21) -> pd.Series:
    """
    隔夜報酬的短期持續（Zhang, Tsai, Weng & Tsai 2023，台灣；Aboody 等 2018）：最近 n 個交易日（含 d）
    隔夜異常報酬的累積。隔夜報酬被文獻當個股情緒代理，短期持續、長期反轉；候選的 `mom` 跳過的最近一個月，
    這裡只拿它的隔夜那一半回來。
    """
    sl, _ = _window(mkt, d, n)
    if sl is None:
        return pd.Series(dtype=float)
    seg = mkt.ar_over.iloc[sl]
    return seg.sum(min_count=int(n * 0.8)).dropna()


def signal_illiq(mkt: Market, d: pd.Timestamp, n: int = 252) -> pd.Series:
    """
    Amihud (2002) 非流動性：過去 n 個交易日 |日報酬| ÷ 成交金額 的平均取 log。值高 = 單位成交金額推動的價格變動大 = 不流動；
    文獻說預期報酬較高。在流動性前 300 的池子裡，這是往池內相對小、相對不流動的那端偏。
    """
    sl, _ = _window(mkt, d, n + 1)
    if sl is None:
        return pd.Series(dtype=float)
    r = np.log(mkt.adj.iloc[sl]).diff().iloc[1:].abs()
    tv = mkt.turnover.iloc[sl].iloc[1:].where(lambda x: x > 0)
    ratio = r / tv
    cnt = ratio.count()
    return np.log(ratio.mean().where(cnt >= int(n * 0.8)).replace(0, np.nan)).dropna()


# ── 第六批（Iteration 72）：產業與季節性 ─────────────────────────────────────

INDUSTRY_MIN_MEMBERS = 5


def _industry_of(mkt: Market, d: pd.Timestamp) -> pd.Series:
    """在市股票 → 產業別（market_universe.industry_type）；沒有產業欄位或產業為空的回空。"""
    if 'industry_type' not in mkt.meta.columns:
        return pd.Series(dtype=object)
    ind = mkt.meta.loc[mkt.active_on(d), 'industry_type'].dropna()
    return ind[ind.astype(str).str.strip() != '']


def signal_indmom(mkt: Market, d: pd.Timestamp) -> pd.Series:
    """
    產業動能（Moskowitz & Grinblatt 1999）：同產業所有在市股票的 12-1 動能（`mom`）等權平均，產業要有 ≥ INDUSTRY_MIN_MEMBERS 檔有值；
    每檔股票拿自己產業的值。上市與上櫃各自的產業分類原樣用（名稱不同就是不同組）。
    """
    mom = signal_mom(mkt, d)
    ind = _industry_of(mkt, d)
    both = mom.index.intersection(ind.index)
    if len(both) == 0:
        return pd.Series(dtype=float)
    df = pd.DataFrame({'mom': mom.reindex(both), 'ind': ind.reindex(both)})
    g = df.groupby('ind')['mom']
    avg = g.mean().where(g.count() >= INDUSTRY_MIN_MEMBERS)
    return df['ind'].map(avg).dropna()


def signal_relmom(mkt: Market, d: pd.Timestamp) -> pd.Series:
    """扣掉產業的個股動能（Grundy & Martin 2001 的「stock-specific」精神，用產業平均當代理）：`mom` − `indmom`。"""
    im = signal_indmom(mkt, d)
    if im.empty:
        return pd.Series(dtype=float)
    return (signal_mom(mkt, d).reindex(im.index) - im).dropna()


def signal_seas(mkt: Market, d: pd.Timestamp, lags: tuple = (1, 2, 3), day: int = 11) -> pd.Series:
    """
    同月季節性（Heston & Sadka 2008；Keloharju, Linnainmaa & Nyberg 2016）：過去 1～3 年「同一個調倉月」
    （前 k 年同月 day 日之後第一個交易日起、到次月 day 日之後第一個交易日止）的累積異常報酬，有幾年算幾年（≥ 1）平均。
    每個窗口要有 ≥ 80% 的交易日有值。只用 d 以前的資料（窗口都在一年以前）。
    """
    days = pd.DatetimeIndex(mkt.days)
    parts = []
    for k in lags:
        y, m = d.year - k, d.month
        y2, m2 = (y, m + 1) if m < 12 else (y + 1, 1)
        start = pd.Timestamp(year=y, month=m, day=day)
        if start < days[0]:                      # 窗口起點早於資料起點：半截窗口不算（strategy-critic，Iteration 72）
            continue
        s = days.searchsorted(start)
        e = days.searchsorted(pd.Timestamp(year=y2, month=m2, day=day))
        if s >= e or e > len(days) or days[min(e, len(days) - 1)] >= d:
            continue
        seg = mkt.ar.iloc[s + 1:e + 1]           # 訊號日收盤之後到下一個訊號日收盤
        if len(seg) < 10:
            continue
        parts.append(seg.sum(min_count=int(len(seg) * 0.8)))
    if not parts:
        return pd.Series(dtype=float)
    return pd.concat(parts, axis=1).mean(axis=1).dropna()


# ── 第七批（Iteration 73）：法人買賣超 ──────────────────────────────────────────

INSTI_COLS = ('foreign_net', 'trust_net')


def needs_institutional(signal: str) -> bool:
    return any(p in signal.split('+') for p in ('fflow', 'tflow'))


def load_institutional(start: date, end: date, extra_days: int = 60) -> dict:
    """market_institutional_daily → {'foreign_net': 寬表, 'trust_net': 寬表}（index 交易日、columns 股票；單位股）。start 往前多拉 extra_days 給 21 日窗口。
    交易所檔沒列的股票日在寬表裡是缺值、不是 0（`_flow` 的 80% 門檻會把常缺的股票剔除）；候選池（流動性前 300）內缺列 0.06%，無影響；
    若將來擴到名次 1,000 以外（缺 31%）要先決定缺列是否視為 0（Iteration 73 結果檔第三節）。"""
    since = start - timedelta(days=extra_days)
    with get_conn() as conn:
        df = pd.read_sql("SELECT stock_id, trade_date, foreign_net, trust_net FROM market_institutional_daily WHERE trade_date BETWEEN %s AND %s",
                         conn, params=(since, end))
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    out = {}
    for c in INSTI_COLS:
        out[c] = df.pivot(index='trade_date', columns='stock_id', values=c).sort_index().astype(float)
    return out


def _flow(mkt: Market, d: pd.Timestamp, col: str, n: int = 21) -> pd.Series:
    """
    法人淨買超占成交金額的比例（Iteration 73 事前登記）：最近 n 個交易日（含 d）Σ(淨買超股數 × 收盤價) ÷ Σ 成交金額。
    成交股數沒載進 Market，所以用金額近似；兩邊都要 ≥ 80% 的交易日有值。沒載法人表（mkt.insti 為 None）回空。
    """
    insti = getattr(mkt, 'insti', None)
    if not insti or col not in insti:
        return pd.Series(dtype=float)
    sl, _ = _window(mkt, d, n)
    if sl is None:
        return pd.Series(dtype=float)
    days = mkt.adj.index[sl]
    net = insti[col].reindex(index=days, columns=mkt.close.columns)
    px = mkt.close.loc[days]
    tv = mkt.turnover.loc[days].where(lambda x: x > 0)
    amt = (net * px)
    ok = (amt.count() >= int(n * 0.8)) & (tv.count() >= int(n * 0.8))
    ratio = amt.sum() / tv.sum().replace(0, np.nan)
    return ratio.where(ok).dropna()


def signal_fflow(mkt: Market, d: pd.Timestamp) -> pd.Series:
    """外資（含外資自營商）最近 21 日淨買超占成交金額的比例（Barber 等 2009；P18）。"""
    return _flow(mkt, d, 'foreign_net')


def signal_tflow(mkt: Market, d: pd.Timestamp) -> pd.Series:
    """投信最近 21 日淨買超占成交金額的比例（P18）。"""
    return _flow(mkt, d, 'trust_net')


# ── 第八批（Iteration 78）：波動處理的動能 ────────────────────────────────────

MOMX_VOL_CUT = 0.9      # `momx`：同窗口波動在全市場最高十分位的股票不給值（文獻分組慣例，不調）


def _mom_and_vol(mkt: Market, d: pd.Timestamp, long_days: int = 252, skip_days: int = 21):
    """`mom` 同一個 12-1 窗口的累積異常報酬與每日異常報酬標準差（都要 ≥ 80% 交易日有值）；歷史不足回 (None, None)。"""
    sl = _mom_window(mkt, d, long_days, skip_days)
    if sl is None:
        return None, None
    seg = mkt.ar.iloc[sl]
    need = int(len(seg) * 0.8)
    m = seg.sum(min_count=need)
    sd = seg.std().where(seg.count() >= need)
    return m, sd


def signal_vmom(mkt: Market, d: pd.Timestamp) -> pd.Series:
    """
    波動率調整動能（Huang, Pan & Wang 2026；Lin 等 2020；TEJ「波動率調整動能」）：`mom` ÷ 同窗口每日異常報酬標準差。
    同樣的動能分數下波動低的排前面；台股文獻說極端強勢股波動大、之後失去動能，這個定義直接把它們往後排。
    """
    m, sd = _mom_and_vol(mkt, d)
    if m is None:
        return pd.Series(dtype=float)
    return (m / sd.where(sd > 0)).dropna()


def signal_momx(mkt: Market, d: pd.Timestamp, cut: float = MOMX_VOL_CUT) -> pd.Series:
    """
    去極端波動的動能（Lin, Xia, Yang & Yang 2020；Yang & Zhang 2019）：`mom`，但同窗口波動在全市場（有 mom 值的股票）最高 (1−cut) 分位的股票不給值。
    分位在全市場算、不在候選池內算（訊號函式看不到池），所以池內被排除的比例不一定剛好 10%。
    """
    m, sd = _mom_and_vol(mkt, d)
    if m is None:
        return pd.Series(dtype=float)
    both = m.notna() & sd.notna()
    if both.sum() == 0:
        return pd.Series(dtype=float)
    thr = sd[both].quantile(cut)
    return m[both & (sd <= thr)]


# ── 第九批（Iteration 80）：價值——交易所估值表（Iteration 78 的 market_valuation_daily）──

VAL_COLS = ('dividend_yield', 'pe')
DY_MAX = 30.0           # 殖利率 > 30% 不給值：2018-01～2024-09 有 2,148 列、17 檔（0.08%），查過是一次性大額股利（例如 8913 每股 113.8 元對股價 15 元；Iteration 80 登記檔）
VAL_MAX_LAG = 5         # 訊號日沒有估值列時，往前最多沿用 5 個交易日


def needs_valuation(signal: str) -> bool:
    return any(p in signal.split('+') for p in ('dy', 'ep'))


def load_valuation(start: date, end: date, extra_days: int = 15) -> dict:
    """market_valuation_daily → {'dividend_yield': 寬表, 'pe': 寬表}（index 交易日、columns 股票）。殖利率是交易所給的百分比值；本益比虧損為缺值。"""
    since = start - timedelta(days=extra_days)
    with get_conn() as conn:
        df = pd.read_sql("SELECT stock_id, trade_date, dividend_yield, pe FROM market_valuation_daily WHERE trade_date BETWEEN %s AND %s",
                         conn, params=(since, end))
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    out = {}
    for c in VAL_COLS:
        out[c] = df.pivot(index='trade_date', columns='stock_id', values=c).sort_index().astype(float)
    return out


def _val_on(mkt: Market, d: pd.Timestamp, col: str, max_lag: int = VAL_MAX_LAG) -> pd.Series:
    """訊號日 d 的估值：交易所當天收盤後公布、以當天收盤價算，訊號在 d 收盤、次日開盤成交。上市殖利率與兩市本益比點時；
    櫃買殖利率整年固定、年初就含當年才決議的股利（Iteration 80 val-pit-check-80），`dy` 對上櫃股在公告前有前視。
    d 沒有列就沿用最近 max_lag 個交易日內的最後一筆；沒掛估值表（mkt.val 為 None）回空。"""
    val = getattr(mkt, 'val', None)
    if not val or col not in val:
        return pd.Series(dtype=float)
    i = int(np.searchsorted(mkt.days, np.datetime64(d), side='right'))
    if i == 0:
        return pd.Series(dtype=float)
    lo = pd.Timestamp(mkt.days[max(i - 1 - max_lag, 0)])
    sub = val[col].loc[lo:d]
    if sub.empty:
        return pd.Series(dtype=float)
    return sub.ffill().iloc[-1].dropna()


def signal_dy(mkt: Market, d: pd.Timestamp) -> pd.Series:
    """殖利率（交易所公布值 ÷ 收盤價；上市檔依最近公告股利、櫃買檔整年固定且年初含未公告的股利——Iteration 80 val-pit-check-80；Hsu 等 2015：台股 D/P 是好的價值代理）。> DY_MAX 視為一次性股利不給值；0 照給（排最後）。"""
    s = _val_on(mkt, d, 'dividend_yield')
    return s[s <= DY_MAX]


def signal_ep(mkt: Market, d: pd.Timestamp) -> pd.Series:
    """益本比 = 1 ÷ 本益比（交易所依最近四季每股盈餘；Hsu 等 2015：台股 E/P 比 B/M 好）。虧損的交易所不印本益比 → 沒有值、不進排名。"""
    pe = _val_on(mkt, d, 'pe')
    pe = pe[pe > 0]
    return 1.0 / pe


def market_state_up(mkt: Market, d: pd.Timestamp, lookback_days: int = 252) -> Optional[bool]:
    """
    市場狀態（Cooper, Gutierrez & Hameed 2004；Du, Huang & Liao 2009 對台股）：0050 過去 lookback_days 個交易日的報酬 ≥ 0 為 UP。
    文獻用三年；Iteration 66 事前決定先用一年，是為了和候選用同一個載入範圍（不暖機，只多載 130 天）。
    三年期（Iteration 67，`~up3`）用 mkt.bench_hist（0050 從 stock_daily_prices 另外載的長序列，見 load_bench_history）算，
    全市場載入範圍不變。歷史不足回 None（不閘門）。
    """
    hist = getattr(mkt, 'bench_hist', None)
    if hist is not None:
        hist = hist[hist.index <= d]
        if len(hist) <= lookback_days:
            return None
        now, before = hist.iloc[-1], hist.iloc[-1 - lookback_days]
    else:
        i = int(np.searchsorted(mkt.days, np.datetime64(d), side='right')) - 1
        if i - lookback_days < 0 or BENCH not in mkt.adj.columns:
            return None
        now, before = mkt.adj[BENCH].iloc[i], mkt.adj[BENCH].iloc[i - lookback_days]
    if pd.isna(now) or pd.isna(before) or before <= 0:
        return None
    return bool(now / before - 1 >= 0)


def load_bench_history(start: date, years: int = 4) -> pd.Series:
    """0050 還原收盤的長序列（start 往前 years 年），給三年期閘門用；index 是交易日。"""
    since = date(start.year - years, start.month, 1)
    with get_conn() as conn:
        df = pd.read_sql("SELECT trade_date, adj_close FROM stock_daily_prices WHERE stock_id = %s AND trade_date >= %s AND adj_close > 0 ORDER BY trade_date",
                         conn, params=(BENCH, since))
    s = pd.Series(df['adj_close'].astype(float).values, index=pd.to_datetime(df['trade_date']))
    return s[~s.index.duplicated()]


STATE_GATE = '~up'    # 成分訊號加這個後綴：只在市場狀態 UP 時參與排名，DOWN 時整個成分拿掉（其餘成分照常）
STATE_GATES = {'~up3': 756, '~up': 252}    # 後綴 → lookback（長的先比對，免得 ~up3 被當成 ~up）


def needs_bench_history(signal: str) -> bool:
    """三年期閘門需要比載入範圍更長的 0050 歷史。"""
    return '~up3' in signal

SINGLE_SIGNALS = ('sue', 'win', 'ar0', 'mom', 'win3', 'lowvol', 'hi52', 'rev1m', 'volchg', 'rev_accel', 'rev_streak',
                  'resmom', 'rev_yoy3', 'momrev', 'cont', 'imom', 'mom127', 'ovn1m', 'illiq', 'indmom', 'relmom', 'seas', 'fflow', 'tflow',
                  'vmom', 'momx', 'dy', 'ep')


TSMC_WEIGHT_FALLBACK = 0.35       # 估不出來時的固定假設：全市場日線從 2018-01-02 起、迴歸要 200 列，所以 2018-10-26 前都用它（Iteration 67 實測）；之後一律用估計值


def estimate_tsmc_weight(mkt: Market, d: pd.Timestamp, window: int = 250, top_n: int = 100,
                         lo: float = 0.20, hi: float = 0.70, min_days: int = 120) -> Optional[float]:
    """
    台積電在 0050 裡的權重（沒有持股權重表時的估計）：
    用 d 以前 window 個交易日，把 0050 的日報酬對「台積電日報酬」與「流動性前 top_n（不含台積電）等權日報酬」做 OLS，
    台積電的係數就是權重估計（夾在 [lo, hi]）。只用 d 以前的資料，沒有前視。
    """
    i = int(np.searchsorted(mkt.days, np.datetime64(d), side='right'))
    if BENCH not in mkt.adj.columns or TSMC not in mkt.adj.columns:
        return None
    window = min(window, i - 1)
    if window < min_days:
        return None
    lr = np.log(mkt.adj.iloc[i - window - 1:i]).diff().iloc[1:]
    b, t = lr[BENCH], lr[TSMC]
    liq = mkt.liq.iloc[i - 1].drop(labels=[BENCH, TSMC], errors='ignore').dropna().sort_values(ascending=False)
    others = lr[liq.index[:top_n]].mean(axis=1)
    x = pd.concat([t, others], axis=1).dropna()
    y = b.reindex(x.index)
    ok = y.notna()
    x, y = x[ok], y[ok]
    if len(y) < window * 0.8:
        return None
    X = np.column_stack([np.ones(len(x)), x.values])
    beta, *_ = np.linalg.lstsq(X, y.values, rcond=None)
    return float(min(hi, max(lo, beta[1])))


def _single(signal: str, mkt: Market, sur: pd.DataFrame, d: pd.Timestamp) -> pd.Series:
    if signal == 'sue':
        return signal_sue(sur, d)
    if signal == 'win':
        return signal_win(mkt, d)
    if signal == 'ar0':
        return signal_ar0(sur, mkt, d)
    if signal == 'mom':
        return signal_mom(mkt, d)
    if signal == 'win3':
        return signal_win3(mkt, d)
    if signal == 'lowvol':
        return signal_lowvol(mkt, d)
    if signal == 'hi52':
        return signal_hi52(mkt, d)
    if signal == 'rev1m':
        return signal_rev1m(mkt, d)
    if signal == 'volchg':
        return signal_volchg(mkt, d)
    if signal == 'rev_accel':
        return signal_rev_accel(sur, d)
    if signal == 'rev_streak':
        return signal_rev_streak(sur, d)
    if signal == 'resmom':
        return signal_resmom(mkt, d)
    if signal == 'rev_yoy3':
        return signal_rev_yoy3(sur, d)
    if signal == 'momrev':
        return signal_momrev(mkt, sur, d)
    if signal == 'cont':
        return signal_cont(mkt, d)
    if signal == 'imom':
        return signal_imom(mkt, d)
    if signal == 'mom127':
        return signal_mom127(mkt, d)
    if signal == 'ovn1m':
        return signal_ovn1m(mkt, d)
    if signal == 'illiq':
        return signal_illiq(mkt, d)
    if signal == 'indmom':
        return signal_indmom(mkt, d)
    if signal == 'relmom':
        return signal_relmom(mkt, d)
    if signal == 'seas':
        return signal_seas(mkt, d)
    if signal == 'fflow':
        return signal_fflow(mkt, d)
    if signal == 'tflow':
        return signal_tflow(mkt, d)
    if signal == 'vmom':
        return signal_vmom(mkt, d)
    if signal == 'momx':
        return signal_momx(mkt, d)
    if signal == 'dy':
        return signal_dy(mkt, d)
    if signal == 'ep':
        return signal_ep(mkt, d)
    raise ValueError(f'未知訊號 {signal}')


def _gated_parts(signal: str, mkt: Market, d: pd.Timestamp) -> list[str]:
    """拆 'a+b~up' 成成分清單；帶 ~up（一年）或 ~up3（三年）的成分只在市場狀態 UP（或算不出狀態）時留下。"""
    parts, states = [], {}
    for p in signal.split('+'):
        for suffix, lookback in STATE_GATES.items():
            if p.endswith(suffix):
                if suffix not in states:
                    states[suffix] = market_state_up(mkt, d, lookback)
                p = None if states[suffix] is False else p[:-len(suffix)]
                break
        if p is not None:
            parts.append(p)
    return parts


def scores_on(signal: str, mkt: Market, sur: pd.DataFrame, d: pd.Timestamp, ids: pd.Index) -> pd.Series:
    """單一訊號直接回原值；'a+b' 是各訊號在候選池內的百分位排名平均（每個成分都要有值）。
    成分後綴 `~up`（STATE_GATE）：市場 DOWN 時拿掉那個成分；全部拿掉就回空（那個月不調倉）。"""
    parts = _gated_parts(signal, mkt, d)
    if not parts:
        return pd.Series(dtype=float)
    if len(parts) == 1:
        return _single(parts[0], mkt, sur, d).reindex(ids).dropna()
    ranks = [_single(p, mkt, sur, d).reindex(ids).rank(pct=True) for p in parts]
    return pd.concat(ranks, axis=1).dropna().mean(axis=1)


def _weights(keep: list, total: float, weighting: str, liq: Optional[pd.Series], cap: float = 0.10) -> dict:
    """equal：等權；liq：按 60 日成交金額比例、單檔上限 cap（超過的部分按比例分給其他）。"""
    if not keep:
        return {}
    if weighting == 'liq' and liq is not None:
        w = liq.reindex(keep).fillna(0.0).clip(lower=0.0)
        w = w / w.sum() if w.sum() > 0 else pd.Series(1.0 / len(keep), index=keep)
        for _ in range(5):
            over = w > cap
            if not over.any():
                break
            excess = (w[over] - cap).sum()
            w[over] = cap
            rest = ~over
            if w[rest].sum() > 0:
                w[rest] += excess * w[rest] / w[rest].sum()
        return {s: float(w[s] * total) for s in keep}
    return {s: total / len(keep) for s in keep}


def build_targets(scores: pd.Series, prev_holdings: list, top_n: int = 20, buffer: int = 40,
                  tsmc_weight: Optional[float] = None, weighting: str = 'equal', liq: Optional[pd.Series] = None,
                  tranche_new: Optional[int] = None, release: Optional[list] = None) -> pd.DataFrame:
    """
    排名 → 目標權重。
    一般模式：上期持股只要還在前 buffer 名就留著，空位由排名最高的新股補。
    分批模式（tranche_new 給了）：release 是這個月到期要賣的那一批，其餘上期持股照留（不看排名），
    只挑 tranche_new 檔排名最高、目前沒持有的新股——每月只換 1/K，年換手壓到 K 分之一。
    台積電不參與排名；tsmc_weight 給了就固定那個權重，其餘 (1 − w) 分給選出的股票。
    """
    ranked = scores.sort_values(ascending=False)
    rank = pd.Series(np.arange(1, len(ranked) + 1), index=ranked.index)
    if tranche_new is not None:
        rel = set(release or [])
        keep = [s for s in prev_holdings if s not in rel]
        n_new = max(tranche_new, top_n - len(keep)) if len(keep) < top_n - tranche_new else tranche_new
        added = 0
        for s in ranked.index:
            if added >= n_new or len(keep) >= top_n:
                break
            if s not in keep:
                keep.append(s)
                added += 1
    else:
        keep = [s for s in prev_holdings if s in rank.index and rank[s] <= buffer][:top_n]
        for s in ranked.index:
            if len(keep) >= top_n:
                break
            if s not in keep:
                keep.append(s)
    w_t = float(tsmc_weight or 0.0)
    rows = []
    if keep:
        wmap = _weights(keep, 1.0 - w_t, weighting, liq)
        rows = [{'stock_id': s, 'rank': int(rank[s]) if s in rank.index else None,
                 'signal_value': float(ranked[s]) if s in ranked.index else None, 'target_weight': wmap[s]} for s in keep]
    if w_t > 0:
        rows.append({'stock_id': TSMC, 'rank': None, 'signal_value': None, 'target_weight': w_t})
    return pd.DataFrame(rows, columns=['stock_id', 'rank', 'signal_value', 'target_weight'])
