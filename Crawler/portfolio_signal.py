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
        m = pd.read_sql("SELECT stock_id, listing_date, delisted_date FROM market_universe", conn)
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


SINGLE_SIGNALS = ('sue', 'win', 'ar0', 'mom', 'win3')


TSMC_WEIGHT_FALLBACK = 0.35       # 歷史不足 120 個交易日時（2018 上半年）用的固定假設；之後一律用估計值


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
    raise ValueError(f'未知訊號 {signal}')


def scores_on(signal: str, mkt: Market, sur: pd.DataFrame, d: pd.Timestamp, ids: pd.Index) -> pd.Series:
    """單一訊號直接回原值；'a+b' 是各訊號在候選池內的百分位排名平均（每個成分都要有值）。"""
    parts = signal.split('+')
    if len(parts) == 1:
        return _single(signal, mkt, sur, d).reindex(ids).dropna()
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
