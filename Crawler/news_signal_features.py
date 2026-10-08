"""
新聞訊號特徵（Iteration 47）
──────────────────────────
把「新聞與股價關聯性」研究方案的六個可量化維度，做成統一面板的兩個區塊：

    news   媒體報導：報導強度、異常注意力、情緒、新穎度、不確定性、MOPS 重大訊息
    event  排程型事件：月營收意外程度（SUE）、公布日反應、距公布天數

## 時序（N0 關卡：新聞在 t 日盤後才可得？）

`news_price_link.effective_date` 已依 13:30 規則歸日：13:30 前發布歸當日，之後歸下一交易日。
本模組在交易日 D 那一列只用 **effective_date ≤ D** 的新聞——D 收盤後才發布的新聞
會歸到 D+1，D 這一列看不到。代價是 20:00 投票時「今天傍晚的新聞」還沒進特徵；
好處是不可能洩漏（D+1 那列包含 D+1 早上 13:30 前的新聞，拿來預測 D+1 就是洩漏）。

營收事件同理：t=0 用 `revenue_event_study.event_day` 同一條規則（公布時戳 13:30 前歸當日，
否則下一交易日；只有日期的視為盤後）。距公布天數與 AR₀ 只在 t=0 之後的列才有值。

## 沒有新聞 ≠ 中性（方案文件第 06 節）

情緒、新穎度、不確定性在沒有新聞的日子是 NaN，不填 0、不填中位數。
報導強度與異常注意力是 0——「今天沒人報導」是可觀察的事實，不是未知。
樹模型（HistGradientBoosting）原生處理缺失，但方案警告「模型會把有無新聞當特徵」，
所以方向類模型（新聞語調）只在有新聞的列上訓練與預測，見 train_news_models.py。

## 維度定義

    ns_n_articles      當日代表則數（去重後 canonical）              報導強度
    ns_n_sources       當日覆蓋媒體家數
    ns_abn_attn        log1p(當日則數) − log1p(前 60 交易日日均則數)   異常注意力（Da, Engelberg & Gao 2011）
    ns_attn_3d         近 3 日則數 對 60 日日均×3 的 log 比
    ns_sent            當日字典情緒均值（無新聞 NaN）                  情緒（Tetlock 2007；字典 = model2_news）
    ns_sent_3d         1／0.6／0.3 衰減加權情緒
    ns_strong_kw       強效關鍵字淨命中
    ns_novelty         1 − 標題與該股前 5 個新聞日標題的最大字元二元組 Jaccard   新穎度（Tetlock 2011：陳舊新聞被過度反應）
    ns_uncertainty     避險／條件用語每千字密度                        不確定性（Loughran & McDonald 2011 的中文近似）
    ns_has_news        當日有無新聞
    ns_mops_nonroutine 非例行重大訊息則數（排除注意交易）              MopsEventStudy：波動訊號
    ns_mops_attention  注意交易／處置公告則數（內生，另列不混）

    ev_sue             最近一次月營收 SUE（surprise ÷ 24 個月標準差）  意外程度 ★
    ev_yoy             最近一次 YoY（log）
    ev_yoy_extreme     YoY 落在該股歷史前 20%（RevenueEventStudy_universe：極端 YoY 反轉）
    ev_days_since_rev  距最近營收公布 t=0 的交易日數（上限 40）
    ev_rev_ar0         公布日 AR₀（等權追蹤股基準）；universe 研究：AR₀ 對 CAR[1,20] 係數 +0.41（t 4.0）
    ev_in_window       1 ≤ 距公布天數 ≤ 20（漂移窗口內）
"""

import logging
import re
from datetime import date, time

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

NEWS_FEATURES = [
    'ns_n_articles', 'ns_n_sources', 'ns_abn_attn', 'ns_attn_3d',
    'ns_sent', 'ns_sent_3d', 'ns_strong_kw', 'ns_novelty', 'ns_uncertainty',
    'ns_has_news', 'ns_mops_nonroutine', 'ns_mops_attention',
]
EVENT_FEATURES = [
    'ev_sue', 'ev_yoy', 'ev_yoy_extreme', 'ev_days_since_rev', 'ev_rev_ar0', 'ev_in_window',
]

# 每日有無新聞以外的欄位，沒有新聞時一律 NaN（不是 0）
_NAN_WITHOUT_NEWS = ['ns_sent', 'ns_sent_3d', 'ns_novelty', 'ns_uncertainty']

ATTN_WINDOW = 60          # 異常注意力的基準視窗（交易日）
ATTN_MIN = 20
DECAY = (1.0, 0.6, 0.3)   # 與 model2_news.DECAY_WEIGHTS 一致
REV_WINDOW = 20           # 漂移窗口（交易日）
REV_CAP = 40
SUE_MIN_HISTORY = 12
CLOSE_TW = time(13, 30)

# 避險／條件用語：中文財經新聞裡「還沒確定」的說法。這是 L&M 不確定性詞表的中文近似，
# 不是權威詞典——方案文件第 05 節說中文財經詞典得自建，這裡先用可解釋的一小份。
UNCERTAINTY_TERMS = [
    '可能', '或許', '預期', '預估', '估計', '若', '恐', '傳出', '傳聞', '據悉', '據傳', '市場傳',
    '不確定', '觀望', '疑似', '尚未', '未定', '擬', '考慮', '評估中', '恐怕', '大概', '有機會',
    '有望', '或將', '預計', '不排除', '取決', '看法分歧', '待觀察', '變數',
]
_UNC_RX = re.compile('|'.join(map(re.escape, UNCERTAINTY_TERMS)))
NEWS_SINCE = '2023-09-01'


def _bigrams(text: str) -> set:
    t = re.sub(r'[\s\W_]+', '', text or '')
    return {t[i:i + 2] for i in range(len(t) - 1)}


def novelty_scores(df: pd.DataFrame, lookback_days: int = 5) -> pd.Series:
    """
    每則新聞的新穎度 = 1 − 與該股**前 lookback_days 個新聞日**所有標題的最大 Jaccard（字元二元組）。
    只看標題：內文常是同一篇通稿改寫，標題才是「這則講了什麼」。第一則永遠是 1。
    df 需含 stock_id、effective_date、title；回傳與 df 對齊的 Series。
    （去重群 dedup_group_id 幾乎每則一群，拿它算新穎度恆為 1，所以不用。）
    """
    out = pd.Series(np.nan, index=df.index, dtype=float)
    for _sid, g in df.groupby('stock_id', sort=False):
        g = g.sort_values('effective_date')
        history = []                       # [(date, [每則標題的二元組集合]), ...] 只留最近 lookback_days 個日子
        for d, sub in g.groupby('effective_date', sort=True):
            prior = [bg for _hd, sets in history for bg in sets]     # 逐則比，不是跟整天的聯集比
            todays = []
            for idx, title in zip(sub.index, sub['title']):
                bg = _bigrams(title)
                if not bg:
                    out[idx] = np.nan
                    continue
                best = 0.0
                for pb in prior:
                    if not pb:
                        continue
                    j = len(bg & pb) / len(bg | pb)
                    if j > best:
                        best = j
                out[idx] = 1.0 - best
                todays.append(bg)
            history.append((d, todays))
            history = history[-lookback_days:]
    return out


def uncertainty_density(text: str) -> float:
    """避險／條件用語每千字密度。空文本回 NaN。"""
    if not text:
        return np.nan
    n = len(text)
    if n < 20:
        return np.nan
    return 1000.0 * len(_UNC_RX.findall(text)) / n


# ── 資料 ─────────────────────────────────────────────────────────────────────
def load_daily_news(stock_ids=None) -> pd.DataFrame:
    """news_daily_features（每個有新聞的股票日一列）。"""
    from db.connection import get_conn
    sql = """
        SELECT stock_id, effective_date, n_articles, sentiment_mean, strong_kw_hit
          FROM news_daily_features
         WHERE effective_date >= %s
    """
    params = [NEWS_SINCE]
    if stock_ids:
        sql += ' AND stock_id = ANY(%s)'
        params.append([str(s) for s in stock_ids])
    with get_conn() as conn:
        df = pd.read_sql(sql, conn, params=tuple(params))
    df['effective_date'] = pd.to_datetime(df['effective_date'])
    return df


def load_articles(stock_ids=None) -> pd.DataFrame:
    """
    逐則新聞（只取去重後代表則）：新穎度、不確定性、媒體家數要逐則算，日表沒有。
    內文只取前 1200 字——密度指標看的是用語比例，不需要全文。
    """
    from db.connection import get_conn
    sql = """
        SELECT l.ticker AS stock_id, l.effective_date, l.news_id,
               n.platform, COALESCE(n.dedup_group_id::text, n.id::text) AS grp,
               n.title, LEFT(n.content, 1200) AS content
          FROM news_price_link l
          JOIN user_news n ON n.id = l.news_id
         WHERE l.market = 'TW' AND l.effective_date >= %s
           AND COALESCE(n.is_canonical, TRUE)
           AND n.platform <> 'MOPS重大訊息'
    """
    params = [NEWS_SINCE]
    if stock_ids:
        sql += ' AND l.ticker = ANY(%s)'
        params.append([str(s) for s in stock_ids])
    with get_conn() as conn:
        df = pd.read_sql(sql, conn, params=tuple(params))
    df['effective_date'] = pd.to_datetime(df['effective_date'])
    return df


def load_mops(stock_ids=None) -> pd.DataFrame:
    """MOPS 重大訊息的規則分類（mops_event_study.persist 寫的 rule_mops_v1）。"""
    from db.connection import get_conn
    sql = """
        SELECT l.ticker AS stock_id, l.effective_date, f.event_type, f.is_expected
          FROM news_llm_feature f
          JOIN news_price_link l ON l.news_id = f.news_id AND l.market = 'TW'
         WHERE f.model = 'rule_mops_v1' AND l.effective_date >= %s
    """
    params = [NEWS_SINCE]
    if stock_ids:
        sql += ' AND l.ticker = ANY(%s)'
        params.append([str(s) for s in stock_ids])
    with get_conn() as conn:
        df = pd.read_sql(sql, conn, params=tuple(params))
    df['effective_date'] = pd.to_datetime(df['effective_date'])
    return df


def load_revenue(stock_ids) -> pd.DataFrame:
    from db.connection import get_conn
    with get_conn() as conn:
        df = pd.read_sql("""
            SELECT stock_id, revenue_month, revenue, announce_date, announce_ts
              FROM stock_revenue_announce
             WHERE stock_id = ANY(%s) AND revenue IS NOT NULL
             ORDER BY stock_id, revenue_month
        """, conn, params=([str(s) for s in stock_ids],))
    df['revenue_month'] = pd.to_datetime(df['revenue_month'])
    return df


def surprises(rev: pd.DataFrame, min_history: int = SUE_MIN_HISTORY) -> pd.DataFrame:
    """與 revenue_event_study.surprises 同一條定義：surprise = YoY − 近 3 個月 YoY 均值，SUE = ÷ 24 個月標準差。"""
    out = []
    for sid, g in rev.groupby('stock_id'):
        s = g.set_index('revenue_month')['revenue'].astype(float)
        s = s.where(s > 0)
        if s.dropna().empty:
            continue
        idx = pd.date_range(s.index.min(), s.index.max(), freq='MS')
        s = s.reindex(idx)
        lg = np.log(s)
        yoy = lg - lg.shift(12)
        trend = pd.concat([yoy.shift(k) for k in (1, 2, 3)], axis=1).mean(axis=1, skipna=False)
        sur = yoy - trend
        sd = sur.shift(1).rolling(24, min_periods=min_history).std()
        df = pd.DataFrame({'stock_id': sid, 'yoy': yoy, 'sue': sur / sd})
        df.index.name = 'revenue_month'
        out.append(df.reset_index())
    if not out:
        return pd.DataFrame(columns=['stock_id', 'revenue_month', 'yoy', 'sue'])
    res = pd.concat(out, ignore_index=True)
    return res.merge(rev[['stock_id', 'revenue_month', 'announce_date', 'announce_ts']],
                     on=['stock_id', 'revenue_month'], how='left')


def event_day(announce_date, announce_ts, open_days: np.ndarray):
    """公布時點 → t=0 交易日（13:30 前歸當日，否則下一交易日；只有日期視為盤後）。"""
    if pd.isna(announce_date):
        return None
    if pd.notna(announce_ts):
        ts = pd.Timestamp(announce_ts)
        d = ts.normalize()
        if ts.time() < CLOSE_TW and d in open_days:
            return d
        after = d
    else:
        after = pd.Timestamp(announce_date).normalize()
    i = np.searchsorted(open_days, np.datetime64(after), side='right')
    return pd.Timestamp(open_days[i]) if i < len(open_days) else None


# ── 逐股票日的計算（純 pandas，可單元測試）────────────────────────────────────
def daily_news_table(daily: pd.DataFrame, articles: pd.DataFrame, mops: pd.DataFrame) -> pd.DataFrame:
    """
    合成「每個有新聞的股票日」一列的表：
    stock_id, effective_date, n_articles, n_sources, sentiment_mean, strong_kw_hit,
    novelty, uncertainty, mops_nonroutine, mops_attention
    """
    base = daily.rename(columns={'sentiment_mean': 'sent'}).copy()

    if not articles.empty:
        a = articles.copy()
        a['text'] = (a['title'].fillna('') + ' ' + a['content'].fillna(''))
        a['unc'] = a['text'].map(uncertainty_density)
        a['novel'] = novelty_scores(a)
        agg = a.groupby(['stock_id', 'effective_date']).agg(
            n_sources=('platform', 'nunique'), novelty=('novel', 'mean'),
            uncertainty=('unc', 'mean'), n_articles_art=('news_id', 'count')).reset_index()
        base = base.merge(agg, on=['stock_id', 'effective_date'], how='outer')
        # 日表缺（例如尚未重算）時，用逐則統計補則數
        base['n_articles'] = base['n_articles'].fillna(base['n_articles_art'])
        base = base.drop(columns=['n_articles_art'])
    else:
        base['n_sources'] = np.nan
        base['novelty'] = np.nan
        base['uncertainty'] = np.nan

    if not mops.empty:
        m = mops.copy()
        m['attention'] = (m['event_type'] == '注意交易').astype(int)
        m['nonroutine'] = ((~m['is_expected'].astype(bool)) & (m['attention'] == 0)).astype(int)
        magg = m.groupby(['stock_id', 'effective_date']).agg(
            mops_nonroutine=('nonroutine', 'sum'), mops_attention=('attention', 'sum')).reset_index()
        base = base.merge(magg, on=['stock_id', 'effective_date'], how='outer')
    for c in ('mops_nonroutine', 'mops_attention'):
        if c not in base.columns:
            base[c] = 0
        base[c] = base[c].fillna(0)
    base['n_articles'] = base['n_articles'].fillna(0)
    base['n_sources'] = base['n_sources'].fillna(0)
    return base


def attach_news_features(panel: pd.DataFrame, table: pd.DataFrame,
                         date_col: str = 'trade_date') -> pd.DataFrame:
    """把每日新聞表併到面板，並算出以交易日計的滾動維度（異常注意力、3 日情緒）。"""
    p = panel.copy()
    p[date_col] = pd.to_datetime(p[date_col])
    t = table.rename(columns={'effective_date': date_col})
    t = t[t[date_col].notna()]
    p = p.merge(t, on=['stock_id', date_col], how='left')
    p = p.sort_values(['stock_id', date_col])

    g = p.groupby('stock_id', sort=False)
    n = p['n_articles'].fillna(0)
    p['ns_n_articles'] = n
    p['ns_n_sources'] = p['n_sources'].fillna(0)
    p['ns_has_news'] = (n > 0).astype(float)
    base_mean = g['ns_n_articles'].transform(
        lambda s: s.rolling(ATTN_WINDOW, min_periods=ATTN_MIN).mean().shift(1))
    p['ns_abn_attn'] = np.log1p(n) - np.log1p(base_mean)
    sum3 = g['ns_n_articles'].transform(lambda s: s.rolling(3, min_periods=1).sum())
    p['ns_attn_3d'] = np.log1p(sum3) - np.log1p(3 * base_mean)

    p['ns_sent'] = p['sent']
    s0 = p['sent']
    s1, s2 = g['sent'].shift(1), g['sent'].shift(2)
    num = (s0.fillna(0) * DECAY[0] + s1.fillna(0) * DECAY[1] + s2.fillna(0) * DECAY[2])
    den = (s0.notna() * DECAY[0] + s1.notna() * DECAY[1] + s2.notna() * DECAY[2])
    p['ns_sent_3d'] = np.where(den > 0, num / den.replace(0, np.nan), np.nan)
    p['ns_strong_kw'] = p['strong_kw_hit'].fillna(0)
    p['ns_novelty'] = p['novelty']
    p['ns_uncertainty'] = p['uncertainty']
    p['ns_mops_nonroutine'] = p['mops_nonroutine'].fillna(0)
    p['ns_mops_attention'] = p['mops_attention'].fillna(0)

    for c in _NAN_WITHOUT_NEWS:
        p.loc[p['ns_has_news'] == 0, c] = np.nan
    drop = [c for c in ('n_articles', 'n_sources', 'sent', 'strong_kw_hit', 'novelty',
                        'uncertainty', 'mops_nonroutine', 'mops_attention') if c in p.columns]
    return p.drop(columns=drop).reset_index(drop=True)


def attach_event_features(panel: pd.DataFrame, sur: pd.DataFrame,
                          date_col: str = 'trade_date') -> pd.DataFrame:
    """
    月營收事件：每列帶「最近一次已公布」的 SUE／YoY／距公布天數／公布日 AR₀。
    AR₀ 用面板自己算：個股當日報酬 − 全體等權當日報酬（RevenueEventStudy 的等權基準）。
    """
    p = panel.copy()
    p[date_col] = pd.to_datetime(p[date_col])
    p = p.sort_values(['stock_id', date_col]).reset_index(drop=True)
    for c in EVENT_FEATURES:
        p[c] = np.nan
    p['ev_in_window'] = 0.0
    if sur.empty:
        return p

    ret = p.groupby('stock_id')['adj_close'].pct_change()
    mkt = ret.groupby(p[date_col]).transform('mean')
    p['_ar'] = ret - mkt

    open_days = np.sort(p[date_col].unique())
    ev = sur.dropna(subset=['sue']).copy()
    ev['t0'] = [event_day(d, ts, open_days) for d, ts in zip(ev['announce_date'], ev['announce_ts'])]
    ev = ev.dropna(subset=['t0']).sort_values(['stock_id', 't0'])

    # 極端 YoY：該股歷史（只看公布前）YoY 的前 20% ——用擴張分位數避免看未來
    ev['yoy_q80'] = ev.groupby('stock_id')['yoy'].transform(
        lambda s: s.shift(1).expanding(min_periods=SUE_MIN_HISTORY).quantile(0.8))
    ev['yoy_extreme'] = ((ev['yoy'] > ev['yoy_q80']) & ev['yoy_q80'].notna()).astype(float)

    pieces = []
    for sid, g in p.groupby('stock_id', sort=False):
        e = ev[ev['stock_id'] == sid]
        if e.empty:
            pieces.append(g)
            continue
        g = g.copy()
        ar_by_date = dict(zip(g[date_col], g['_ar']))
        dates = g[date_col].values
        # 每個交易日對應「最近一次 t0 ≤ D」的事件
        t0s = e['t0'].values.astype('datetime64[ns]')
        idx = np.searchsorted(t0s, dates.astype('datetime64[ns]'), side='right') - 1
        has = idx >= 0
        ii = np.clip(idx, 0, len(e) - 1)
        g['ev_sue'] = np.where(has, e['sue'].values[ii], np.nan)
        g['ev_yoy'] = np.where(has, e['yoy'].values[ii], np.nan)
        g['ev_yoy_extreme'] = np.where(has, e['yoy_extreme'].values[ii], np.nan)
        t0_of = np.where(has, t0s[ii], np.datetime64('NaT'))
        pos = {d: i for i, d in enumerate(dates)}
        days = np.array([(pos[d] - pos[t]) if (has_i and t in pos) else np.nan
                         for d, t, has_i in zip(dates, t0_of, has)], dtype=float)
        g['ev_days_since_rev'] = np.clip(days, 0, REV_CAP)
        g['ev_rev_ar0'] = [ar_by_date.get(pd.Timestamp(t), np.nan) if has_i else np.nan
                           for t, has_i in zip(t0_of, has)]
        g['ev_in_window'] = ((days >= 1) & (days <= REV_WINDOW)).astype(float)
        pieces.append(g)
    p = pd.concat(pieces).sort_values(['stock_id', date_col]).reset_index(drop=True)
    return p.drop(columns=['_ar'])


# ── 面板掛載入口（panel.py 用）──────────────────────────────────────────────
def attach_news(panel: pd.DataFrame, date_col: str = 'trade_date') -> pd.DataFrame:
    ids = sorted(panel['stock_id'].astype(str).unique())
    daily = load_daily_news(ids)
    arts = load_articles(ids)
    mops = load_mops(ids)
    table = daily_news_table(daily, arts, mops)
    logger.info('[news_signal] 新聞股票日 %d 列、逐則 %d、MOPS %d（%s ~ %s）', len(table), len(arts), len(mops),
                str(table['effective_date'].min())[:10] if len(table) else '—',
                str(table['effective_date'].max())[:10] if len(table) else '—')
    return attach_news_features(panel, table, date_col)


def attach_event(panel: pd.DataFrame, date_col: str = 'trade_date') -> pd.DataFrame:
    ids = sorted(panel['stock_id'].astype(str).unique())
    rev = load_revenue(ids)
    sur = surprises(rev) if not rev.empty else pd.DataFrame()
    logger.info('[news_signal] 營收 %d 列 → SUE %d 筆', len(rev), int(sur['sue'].notna().sum()) if len(sur) else 0)
    return attach_event_features(panel, sur, date_col)


def latest_dimensions(panel: pd.DataFrame) -> list:
    """每檔最新一列的六個維度（供 /news/signals 呈現）。"""
    cols = ['stock_id', 'trade_date'] + NEWS_FEATURES + EVENT_FEATURES
    last = panel.sort_values('trade_date').groupby('stock_id').tail(1)
    out = []
    for _, r in last[[c for c in cols if c in last.columns]].iterrows():
        d = {'stock_id': str(r['stock_id']), 'as_of': str(r['trade_date'])[:10]}
        for c in NEWS_FEATURES + EVENT_FEATURES:
            v = r.get(c)
            d[c] = None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)
        out.append(d)
    return out
