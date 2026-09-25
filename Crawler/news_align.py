"""
新聞日級對齊與歷史特徵（Iteration 38 階段 2d / 2e）
────────────────────────────────────────────────────
方案文件的對齊規則：新聞依市場收盤時間歸屬交易日——收盤前發布歸當日 T，
收盤後或非交易日歸下一交易日。台股 13:30、美股 16:00（紐約）。

三步：
    build_calendar()          從 stock_daily_prices / us_daily_prices 的實際交易日建 trading_calendar
    link_news()               user_news 有個股標記者 → news_price_link (news_id, ticker, market, effective_date)
    compute_daily_features()  news_price_link × user_news → news_daily_features (stock_id, effective_date)

為什麼要這張 news_daily_features：`model2_news._persist_features` 只在跑的當天以
CURRENT_DATE 寫 news_features，關機那天就永遠沒有；回填了 3 年新聞也補不回特徵。
本模組從**發布時間**回算，所以任何一天都可以重算，M2 才有訓練集與走查。

情緒仍用 model2_news 的關鍵字字典（階段 4 換 LLM 特徵時只要加欄位）。

用法：
    python news_align.py --all              # 三步全跑
    python news_align.py --calendar
    python news_align.py --link [--since 2023-09-01]
    python news_align.py --features [--since 2023-09-01]
"""

import argparse
import bisect
import logging
from datetime import date, datetime, time as dtime, timedelta

from db.connection import get_conn

logger = logging.getLogger(__name__)

CLOSE_LOCAL = {'TW': dtime(13, 30), 'US': dtime(16, 0)}
PRICE_TABLES = {'TW': 'stock_daily_prices', 'US': 'us_daily_prices'}


# ── ① 交易日曆 ────────────────────────────────────────────────────────────────
def build_calendar() -> int:
    n = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for market, table in PRICE_TABLES.items():
                cur.execute(f"""
                    INSERT INTO trading_calendar (market, trade_date, is_open, close_time_local)
                    SELECT %s, trade_date, TRUE, %s FROM (SELECT DISTINCT trade_date FROM {table}) d
                    ON CONFLICT DO NOTHING
                """, (market, CLOSE_LOCAL[market]))
                n += cur.rowcount
        conn.commit()
    logger.info('[align] trading_calendar 新增 %d 日', n)
    return n


def load_open_days(market: str) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT trade_date FROM trading_calendar WHERE market=%s AND is_open ORDER BY 1",
                        (market,))
            return [r[0] for r in cur.fetchall()]


def effective_date(published: datetime, open_days: list, market: str = 'TW') -> tuple:
    """
    回傳 (effective_date, lag_days)。published 為該市場當地時間（台股用本地時間即可）。
    收盤前且當日開市 → 當日；否則 → 下一個開市日。
    """
    d = published.date()
    i = bisect.bisect_left(open_days, d)
    if i < len(open_days) and open_days[i] == d and published.time() < CLOSE_LOCAL[market]:
        return d, 0
    # 下一個開市日（嚴格大於 d）
    j = bisect.bisect_right(open_days, d)
    if j >= len(open_days):
        # 日曆還沒有那天（最新新聞落在下一個尚未收盤的交易日）：用日曆外推——
        # 週末跳到週一，其餘視為隔日。假日誤差留待日曆更新後由 --link 重算覆蓋。
        if d.weekday() < 5 and published.time() < CLOSE_LOCAL[market]:
            return d, 0
        nxt = d + timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
        return nxt, (nxt - d).days
    return open_days[j], (open_days[j] - d).days


# ── ② 新聞 → 標的 → 交易日 ──────────────────────────────────────────────────────
def link_news(since: date = None, market: str = 'TW') -> int:
    """user_news 有 tickers 者寫入 news_price_link（upsert：同鍵重算覆蓋）。"""
    open_days = load_open_days(market)
    if not open_days:
        raise RuntimeError('trading_calendar 為空，先跑 build_calendar()')
    n = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, submitted_at, tickers FROM user_news
                WHERE tickers IS NOT NULL AND array_length(tickers, 1) > 0
                  AND submitted_at IS NOT NULL AND (%s::date IS NULL OR submitted_at >= %s::date)
                ORDER BY id
            """, (since, since))
            rows = cur.fetchall()
            for news_id, published, tickers in rows:
                eff, lag = effective_date(published, open_days, market)
                for tk in set(tickers):
                    cur.execute("""
                        INSERT INTO news_price_link
                            (news_id, ticker, market, published_at, effective_date, lag_days, link_reason)
                        VALUES (%s, %s, %s, %s, %s, %s, 'direct_ticker')
                        ON CONFLICT (news_id, ticker, market) DO UPDATE SET
                            published_at = EXCLUDED.published_at,
                            effective_date = EXCLUDED.effective_date,
                            lag_days = EXCLUDED.lag_days
                    """, (news_id, tk, market, published, eff, lag))
                    n += 1
        conn.commit()
    logger.info('[align] news_price_link 寫入 %d 筆（%d 則新聞）', n, len(rows))
    return n


# ── ③ 每日特徵 ────────────────────────────────────────────────────────────────
def compute_daily_features(since: date = None, market: str = 'TW') -> int:
    """
    以 effective_date 聚合：
      本股：n_articles / sentiment_mean / sentiment_sum / n_pos / n_neg / strong_kw_hit
      全市場：market_n_articles / market_sentiment（該 effective_date 全部新聞，含無個股者）
    只算 is_canonical（去重後代表則）；欄位不存在時視為全部 canonical。
    """
    from model2_news import _score_text, _strong_keyword_hits

    open_days = load_open_days(market)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name='user_news' AND column_name='is_canonical'")
            canon_filter = 'AND is_canonical' if cur.fetchone() else ''
            cur.execute(f"""
                SELECT id, title, content, submitted_at FROM user_news
                WHERE submitted_at IS NOT NULL AND (%s::date IS NULL OR submitted_at >= %s::date - 7)
                {canon_filter}
            """, (since, since))
            arts = cur.fetchall()
            cur.execute("""
                SELECT news_id, ticker, effective_date FROM news_price_link
                WHERE market = %s AND (%s::date IS NULL OR effective_date >= %s::date)
            """, (market, since, since))
            links = cur.fetchall()

    # 每則新聞的情緒與全市場歸屬日
    score, kw, eff_of = {}, {}, {}
    for news_id, title, content, published in arts:
        text = (title or '') + ' ' + (content or '')
        score[news_id] = _score_text(text)
        h = _strong_keyword_hits(text)
        kw[news_id] = len(h['pos']) - len(h['neg'])
        eff_of[news_id], _ = effective_date(published, open_days, market)

    market_agg = {}
    for news_id, eff in eff_of.items():
        m = market_agg.setdefault(eff, [0, 0.0])
        m[0] += 1
        m[1] += score[news_id]

    per_stock = {}
    for news_id, ticker, eff in links:
        if news_id not in score:
            continue
        a = per_stock.setdefault((ticker, eff), {'n': 0, 'sum': 0.0, 'pos': 0, 'neg': 0, 'kw': 0})
        s = score[news_id]
        a['n'] += 1
        a['sum'] += s
        a['pos'] += s > 0
        a['neg'] += s < 0
        a['kw'] += kw[news_id]

    n = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for (ticker, eff), a in per_stock.items():
                if since and eff < since:
                    continue
                mk = market_agg.get(eff, [0, 0.0])
                cur.execute("""
                    INSERT INTO news_daily_features
                        (stock_id, effective_date, n_articles, sentiment_mean, sentiment_sum,
                         n_pos, n_neg, strong_kw_hit, market_n_articles, market_sentiment, computed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (stock_id, effective_date) DO UPDATE SET
                        n_articles = EXCLUDED.n_articles, sentiment_mean = EXCLUDED.sentiment_mean,
                        sentiment_sum = EXCLUDED.sentiment_sum, n_pos = EXCLUDED.n_pos,
                        n_neg = EXCLUDED.n_neg, strong_kw_hit = EXCLUDED.strong_kw_hit,
                        market_n_articles = EXCLUDED.market_n_articles,
                        market_sentiment = EXCLUDED.market_sentiment, computed_at = NOW()
                """, (ticker, eff, a['n'], round(a['sum'] / a['n'], 4), round(a['sum'], 4),
                      a['pos'], a['neg'], a['kw'], mk[0], round(mk[1] / mk[0], 4) if mk[0] else None))
                n += 1
        conn.commit()
    logger.info('[align] news_daily_features 寫入 %d 列（%d 則新聞、%d 條連結）', n, len(arts), len(links))
    return n


def run_all(since: date = None) -> dict:
    return {'calendar': build_calendar(), 'links': link_news(since), 'features': compute_daily_features(since)}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--calendar', action='store_true')
    ap.add_argument('--link', action='store_true')
    ap.add_argument('--features', action='store_true')
    ap.add_argument('--since', default=None)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    since = date.fromisoformat(a.since) if a.since else None
    if a.all:
        print(run_all(since))
    else:
        if a.calendar:
            print('calendar', build_calendar())
        if a.link:
            print('links', link_news(since))
        if a.features:
            print('features', compute_daily_features(since))
