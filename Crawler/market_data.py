"""
全市場日線 market_daily_prices：回補、每日更新、公司行動、還原價、資料檢查（Iteration 48，「打敗大盤」階段 1）

兩條資料路線，寫進同一張表、同樣欄位：
    finmind   逐檔 TaiwanStockPrice（免費額度：匿名約 30 次/小時、免費 token 600 次/小時），一檔一次拿 2018 起全部。
              全市場 1,800 檔 = 1,800 次呼叫。可中斷續跑：已有資料的檔跳過。
    exchange  交易所每日檔（scrapers/exchange_daily.py），一天兩次呼叫（上市＋上櫃）拿全市場，不吃額度。
              每日排程用它；回補也可以用它（2018 起約 2,100 個交易日 × 2 次）。
公司行動（除權息、減資）一律從交易所的參考價表來（按月、全市場、不吃額度），寫進既有的
stock_dividend_result / stock_capital_reduction，再用同一套回溯還原演算法算 adj_close。
加權報酬指數（含息大盤）：FinMind TaiwanStockTotalReturnIndex 一次回補，每日從證交所 MI_INDEX 的報酬指數表更新，
存 index_daily_prices，symbol = TAIEX_TR（發行量加權股價指數 = TAIEX）。

用法：
    python market_data.py --backfill --source finmind [--limit N] [--retry-wait 600]
    python market_data.py --backfill --source exchange [--start 2018-01-01] [--end 2026-10-07]
    python market_data.py --events [--start 2018-01-01]       # 除權息＋減資（交易所表，按月）
    python market_data.py --index                              # 加權報酬指數回補（1 次 FinMind 呼叫）
    python market_data.py --rebuild-adj                        # 全市場 adj_close
    python market_data.py --update [--date 2026-10-07]         # 單日（排程用）
    python market_data.py --check                              # 四項偏差檢查
    python market_data.py --status
"""

import argparse
import logging
import time
from datetime import date, datetime, timedelta
from typing import Optional

from psycopg2.extras import execute_values

from db.connection import get_conn
import market_universe
from scrapers import exchange_daily as ex

logger = logging.getLogger(__name__)

PRICE_START = date(2018, 1, 1)
TAIEX_TR = 'TAIEX_TR'
TAIEX = 'TAIEX'
EXCHANGE_DELAY = 3.0          # 交易所兩次呼叫之間（禮貌）
FINMIND_DELAY = 2.0


# ── 寫入 ──────────────────────────────────────────────────────────────────────

def upsert_prices(rows: list[dict]) -> int:
    if not rows:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO market_daily_prices (stock_id, trade_date, open_price, high_price, low_price, close_price,
                    volume, turnover_value, transaction_count, change_value, source)
                VALUES %s
                ON CONFLICT (stock_id, trade_date) DO UPDATE SET
                    open_price = EXCLUDED.open_price, high_price = EXCLUDED.high_price, low_price = EXCLUDED.low_price,
                    close_price = EXCLUDED.close_price, volume = EXCLUDED.volume, turnover_value = EXCLUDED.turnover_value,
                    transaction_count = EXCLUDED.transaction_count, change_value = EXCLUDED.change_value,
                    source = EXCLUDED.source, fetched_at = CURRENT_TIMESTAMP
            """, [(r['stock_id'], r['trade_date'], r.get('open_price'), r.get('high_price'), r.get('low_price'),
                   r['close_price'], r.get('volume'), r.get('turnover_value'), r.get('transaction_count'),
                   r.get('change_value'), r.get('source')) for r in rows], page_size=1000)
        conn.commit()
    return len(rows)


def upsert_index(symbol: str, points: list[tuple]) -> int:
    """points = [(trade_date, close), ...]；指數只有收盤，開高低寫同一值。"""
    pts = [(symbol, d, c, c, c, c, 0) for d, c in points if c is not None]
    if not pts:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO index_daily_prices (symbol, trade_date, open_price, high_price, low_price, close_price, volume)
                VALUES %s ON CONFLICT (symbol, trade_date) DO UPDATE SET
                    open_price = EXCLUDED.open_price, high_price = EXCLUDED.high_price,
                    low_price = EXCLUDED.low_price, close_price = EXCLUDED.close_price
            """, pts, page_size=1000)
        conn.commit()
    return len(pts)


def upsert_reductions(rows: list[dict]) -> int:
    if not rows:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO stock_capital_reduction (stock_id, ex_date, before_price, reference_price, reason)
                VALUES %s ON CONFLICT (stock_id, ex_date) DO UPDATE SET
                    before_price = EXCLUDED.before_price, reference_price = EXCLUDED.reference_price, reason = EXCLUDED.reason
            """, [(r['stock_id'], r['ex_date'], r['before_price'], r['reference_price'], r.get('reason')) for r in rows])
        conn.commit()
    return len(rows)


# ── 交易日 ────────────────────────────────────────────────────────────────────

def trading_days(start: date, end: date) -> list[date]:
    """trading_calendar（market TW，只存開市日）；日曆沒涵蓋的尾段用平日補，交易所回休市就略過。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT trade_date FROM trading_calendar WHERE market = 'TW' AND trade_date BETWEEN %s AND %s ORDER BY 1",
                        (start, end))
            days = [r[0] for r in cur.fetchall()]
            cur.execute("SELECT max(trade_date) FROM trading_calendar WHERE market = 'TW'")
            cal_end = cur.fetchone()[0]
    tail_from = max(start, (cal_end + timedelta(days=1)) if cal_end else start)
    d = tail_from
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def _last_trading_day(today: Optional[date] = None) -> date:
    today = today or date.today()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT max(trade_date) FROM trading_calendar WHERE market = 'TW' AND trade_date <= %s", (today,))
            d = cur.fetchone()[0]
    return d or today


# ── 路線一：FinMind 逐檔回補 ──────────────────────────────────────────────────

def _finmind_price_rows(sid: str, data: list) -> list[dict]:
    rows = []
    for d in data:
        close = ex._num(d.get('close'))
        if close is None:
            continue
        rows.append({'stock_id': sid, 'trade_date': date.fromisoformat(str(d['date'])[:10]),
                     'open_price': ex._num(d.get('open')), 'high_price': ex._num(d.get('max')), 'low_price': ex._num(d.get('min')),
                     'close_price': close, 'volume': ex._int(d.get('Trading_Volume')), 'turnover_value': ex._num(d.get('Trading_money')),
                     'transaction_count': ex._int(d.get('Trading_turnover')), 'change_value': ex._num(d.get('spread')),
                     'source': 'finmind'})
    return rows


def _coverage() -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stock_id, min(trade_date), max(trade_date), count(*) FROM market_daily_prices GROUP BY 1")
            return {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}


def _universe_meta() -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stock_id, listing_date, delisted_date FROM market_universe")
            return {r[0]: (r[1], r[2]) for r in cur.fetchall()}


def pending_ids(start: date = PRICE_START, end: Optional[date] = None) -> list[str]:
    """還沒補到底的股票：下市股補到下市日前 45 天即可（下市前有停止買賣期），在市股補到最近交易日前 7 天；start 之前就下市的不補。"""
    end = end or _last_trading_day()
    meta, cov = _universe_meta(), _coverage()
    out = []
    for sid, (listed, delisted) in sorted(meta.items()):
        if delisted and delisted < start:
            continue
        target = min(delisted, end) if delisted else end
        if listed and listed > target:
            continue
        have = cov.get(sid)
        # 下市股在正式下市日前通常已停止交易幾週（終止上市前的停止買賣期），放寬到 45 天
        if have and have[1] >= target - timedelta(days=45 if delisted else 7):
            continue
        out.append(sid)
    return out


def backfill_finmind(ids: Optional[list] = None, start: date = PRICE_START, retry_wait: int = 600,
                     delay: float = FINMIND_DELAY, limit: int = 0, max_quota_waits: int = 48) -> dict:
    """逐檔抓 TaiwanStockPrice（start 起到今天）。額度用盡就等 retry_wait 秒再試；可隨時中斷，下次從沒補完的檔繼續。"""
    ids = ids if ids is not None else pending_ids(start)
    if limit:
        ids = ids[:limit]
    out = {'done': 0, 'rows': 0, 'failed': [], 'quota_waits': 0, 'total': len(ids)}
    logger.info('[market/finmind] 待補 %d 檔（自 %s）', len(ids), start)
    for i, sid in enumerate(ids, 1):
        for attempt in range(6):
            try:
                data = market_universe.finmind('TaiwanStockPrice', data_id=sid, start_date=start.isoformat(),
                                               end_date=date.today().isoformat())
                n = upsert_prices(_finmind_price_rows(sid, data))
                out['done'] += 1
                out['rows'] += n
                logger.info('[market/finmind] [%d/%d] %s %d 筆', i, len(ids), sid, n)
                break
            except market_universe.QuotaError as e:
                out['quota_waits'] += 1
                if out['quota_waits'] > max_quota_waits:
                    logger.error('[market/finmind] 額度等待超過 %d 次，停止', max_quota_waits)
                    out['failed'].extend(ids[i - 1:])
                    return out
                logger.warning('[market/finmind] [%d/%d] %s 額度問題（%s），等 %d 秒', i, len(ids), sid, e, retry_wait)
                time.sleep(retry_wait)
            except Exception as e:       # noqa: BLE001
                logger.warning('[market/finmind] %s 失敗：%s', sid, e)
                time.sleep(10)
        else:
            out['failed'].append(sid)
        time.sleep(delay)
    out['listing_dates'] = derive_listing_dates(start)
    return out


# ── 路線二：交易所每日檔 ──────────────────────────────────────────────────────

def update_day(d: date, fill_adj: bool = True, universe: Optional[set] = None) -> dict:
    """抓一天的上市＋上櫃全市場行情與加權（報酬）指數。休市回 {'holiday': True}。"""
    rows, indexes = ex.parse_twse_daily(ex.fetch_twse_daily(d))
    if not rows:
        return {'date': d, 'holiday': True}
    time.sleep(1.0)
    tpex_rows = ex.parse_tpex_daily(ex.fetch_tpex_daily(d))
    uni = universe if universe is not None else set(market_universe.ids(include_delisted=True))
    keep = [r for r in rows + tpex_rows if r['stock_id'] in uni]
    n = upsert_prices(keep)
    idx = 0
    if indexes.get(ex.TAIEX_TR_NAME) is not None:
        idx += upsert_index(TAIEX_TR, [(d, indexes[ex.TAIEX_TR_NAME])])
    if indexes.get(ex.TAIEX_NAME) is not None:
        idx += upsert_index(TAIEX, [(d, indexes[ex.TAIEX_NAME])])
    if fill_adj:
        # 最新一列的還原係數必為 1（事件表只收已發生的事件），直接等於收盤；有新事件的股票另外重建
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE market_daily_prices SET adj_close = close_price WHERE trade_date = %s AND adj_close IS NULL", (d,))
            conn.commit()
    return {'date': d, 'holiday': False, 'twse': sum(1 for r in keep if r['source'] == 'twse'),
            'tpex': sum(1 for r in keep if r['source'] == 'tpex'), 'rows': n, 'index': idx,
            'dropped': len(rows) + len(tpex_rows) - len(keep)}


FULL_DAY_MIN_ROWS = 1000      # 一天的列數少於這個，就當這天還沒用交易所檔補過（逐檔路線只會零星寫到）


def _days_have(min_rows: int = FULL_DAY_MIN_ROWS) -> set:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT trade_date FROM market_daily_prices GROUP BY 1 HAVING count(*) >= %s", (min_rows,))
            return {r[0] for r in cur.fetchall()}


def backfill_exchange(start: date = PRICE_START, end: Optional[date] = None, delay: float = EXCHANGE_DELAY,
                      limit: int = 0) -> dict:
    """按交易日抓交易所檔；已有資料的日子跳過，可中斷續跑。結束後要跑 rebuild_adj()。"""
    end = end or date.today()
    have = _days_have()
    days = [d for d in trading_days(start, end) if d not in have]
    if limit:
        days = days[:limit]
    uni = set(market_universe.ids(include_delisted=True))
    out = {'days': 0, 'rows': 0, 'holidays': 0, 'failed': [], 'total': len(days)}
    logger.info('[market/exchange] 待補 %d 個交易日（%s ~ %s）', len(days), start, end)
    for i, d in enumerate(days, 1):
        try:
            r = update_day(d, fill_adj=False, universe=uni)
        except Exception as e:       # noqa: BLE001
            logger.warning('[market/exchange] %s 失敗：%s', d, e)
            out['failed'].append(d)
            time.sleep(delay * 3)
            continue
        if r.get('holiday'):
            out['holidays'] += 1
        else:
            out['days'] += 1
            out['rows'] += r['rows']
        if i % 20 == 0 or i == len(days):
            logger.info('[market/exchange] [%d/%d] %s：%s 列（累計 %d 日 %d 列）', i, len(days), d, r.get('rows', 0), out['days'], out['rows'])
        time.sleep(delay)
    out['listing_dates'] = derive_listing_dates(start)
    return out


# ── 公司行動（交易所參考價表）───────────────────────────────────────────────

def _month_chunks(start: date, end: date):
    cur = date(start.year, start.month, 1)
    while cur <= end:
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        yield max(cur, start), min(nxt - timedelta(days=1), end)
        cur = nxt


def refresh_events(start: date, end: Optional[date] = None, delay: float = EXCHANGE_DELAY) -> dict:
    """除權息（兩市，按月）＋減資（上市，按年）→ 事件表。只收 ex_date ≤ 今天的事件（未來事件會把整段歷史提前縮放）。"""
    import backfill_dividend
    today = date.today()
    end = min(end or today, today)
    uni = set(market_universe.ids(include_delisted=True))
    out = {'dividends': 0, 'reductions': 0, 'stock_ids': set(), 'failed': []}
    for s, e in _month_chunks(start, end):
        rows = []
        for name, fetch, parse in (('twse', ex.fetch_twse_exright, ex.parse_twse_exright),
                                   ('tpex', ex.fetch_tpex_exright, ex.parse_tpex_exright)):
            try:
                rows += [r for r in parse(fetch(s, e)) if r['stock_id'] in uni and r['ex_date'] <= today]
            except Exception as err:       # noqa: BLE001
                logger.warning('[market/events] %s %s~%s 失敗：%s', name, s, e, err)
                out['failed'].append((name, s))
            time.sleep(delay)
        if rows:
            out['dividends'] += backfill_dividend.upsert_dividends(rows)
            out['stock_ids'].update(r['stock_id'] for r in rows)
    # 減資：一年一次呼叫
    y = start.year
    while date(y, 1, 1) <= end:
        s, e = max(date(y, 1, 1), start), min(date(y, 12, 31), end)
        try:
            rows = [r for r in ex.parse_twse_capital_reduction(ex.fetch_twse_capital_reduction(s, e))
                    if r['stock_id'] in uni and r['ex_date'] <= today]
            out['reductions'] += upsert_reductions(rows)
            out['stock_ids'].update(r['stock_id'] for r in rows)
        except Exception as err:       # noqa: BLE001
            logger.warning('[market/events] 減資 %d 失敗：%s', y, err)
            out['failed'].append(('twtauu', s))
        time.sleep(delay)
        y += 1
    out['stock_ids'] = sorted(out['stock_ids'])
    logger.info('[market/events] 除權息 %d 筆、減資 %d 筆、涉及 %d 檔、失敗 %d 段',
                out['dividends'], out['reductions'], len(out['stock_ids']), len(out['failed']))
    return out


# ── 加權報酬指數 ──────────────────────────────────────────────────────────────

def backfill_index(start: date = PRICE_START) -> int:
    """FinMind TaiwanStockTotalReturnIndex（TAIEX）一次回補，1 次呼叫。"""
    data = market_universe.finmind('TaiwanStockTotalReturnIndex', data_id='TAIEX', start_date=start.isoformat(),
                                   end_date=date.today().isoformat())
    pts = [(date.fromisoformat(str(d['date'])[:10]), ex._num(d.get('price'))) for d in data]
    return upsert_index(TAIEX_TR, pts)


# ── 上市日（從第一筆價格推回）────────────────────────────────────────────────

def derive_listing_dates(start: date = PRICE_START, grace_days: int = 10) -> int:
    """listing_date 空的股票：第一筆價格日若明顯晚於資料起點，就當作上市日；起點就有價的股票是 start 以前上市，留空。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE market_universe u SET listing_date = p.first_day, updated_at = CURRENT_TIMESTAMP
                FROM (SELECT stock_id, min(trade_date) AS first_day FROM market_daily_prices GROUP BY 1) p
                WHERE p.stock_id = u.stock_id AND u.listing_date IS NULL AND p.first_day > %s
            """, (start + timedelta(days=grace_days),))
            n = cur.rowcount
        conn.commit()
    return n


# ── 還原價 ────────────────────────────────────────────────────────────────────

def _cum_factors(rows: list[tuple], events: list[tuple]) -> dict:
    """rows=[(trade_date, close)] 升冪；events=[(ex_date, factor, kind)] 升冪 → {trade_date: 累積係數}（與 rebuild_adj_close 同一演算法）。"""
    cum, cum_map = 1.0, {}
    ev_idx = len(events) - 1
    for trade_date, _close in reversed(rows):
        while ev_idx >= 0 and events[ev_idx][0] > trade_date:
            cum *= events[ev_idx][1]
            ev_idx -= 1
        cum_map[trade_date] = cum
    return cum_map


def rebuild_adj(ids: Optional[list] = None) -> int:
    """重算 market_daily_prices.adj_close。沒有事件的股票 adj = close（一句 SQL）；有事件的逐檔批次更新。"""
    import rebuild_adj_close
    ids = ids if ids is not None else market_universe.ids(include_delisted=True)
    events = rebuild_adj_close.load_events(set(ids))
    plain = [sid for sid in ids if sid not in events]
    updated = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            if plain:
                cur.execute("""UPDATE market_daily_prices SET adj_close = close_price
                               WHERE stock_id = ANY(%s) AND (adj_close IS NULL OR adj_close <> close_price)""", (plain,))
                updated += cur.rowcount
        conn.commit()
    for sid in ids:
        evs = events.get(sid)
        if not evs:
            continue
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT trade_date, close_price FROM market_daily_prices WHERE stock_id = %s AND close_price > 0 ORDER BY 1", (sid,))
                rows = cur.fetchall()
                if not rows:
                    continue
                cum = _cum_factors(rows, evs)
                vals = [(sid, d, round(float(c) * cum[d], 4)) for d, c in rows]
                # execute_values 只允許一個 %s：股票代碼放進 VALUES 列裡，不能再當第二個參數
                for i in range(0, len(vals), 2000):
                    execute_values(cur, """
                        UPDATE market_daily_prices AS m SET adj_close = v.adj
                        FROM (VALUES %s) AS v (stock_id, trade_date, adj)
                        WHERE m.stock_id = v.stock_id AND m.trade_date = v.trade_date
                          AND (m.adj_close IS NULL OR m.adj_close <> v.adj)
                    """, vals[i:i + 2000], template='(%s, %s::date, %s::numeric)', page_size=2000)
                    updated += cur.rowcount
            conn.commit()
    logger.info('[market/adj] 重建 %d 列（%d 檔，其中 %d 檔有公司行動）', updated, len(ids), len(ids) - len(plain))
    return updated


# ── 四項偏差檢查 ──────────────────────────────────────────────────────────────

def checks(start: date = PRICE_START) -> list[dict]:
    """回測前的資料檢查；每項 {check, value, ok, note}。ok=None 表示只是數字、不判定。"""
    out = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT count(*), count(*) FILTER (WHERE delisted_date IS NULL),
                                  count(*) FILTER (WHERE delisted_date >= %s) FROM market_universe""", (start,))
            n_all, n_active, n_delisted = cur.fetchone()
            cur.execute("""SELECT count(DISTINCT u.stock_id) FROM market_universe u
                           JOIN market_daily_prices p ON p.stock_id = u.stock_id AND p.trade_date >= %s
                           WHERE u.delisted_date >= %s""", (start, start))
            n_delisted_with_prices = cur.fetchone()[0]
            out.append({'check': 'survivorship', 'value': f'{n_delisted_with_prices}/{n_delisted}',
                        'ok': n_delisted > 0 and n_delisted_with_prices >= 0.5 * n_delisted,
                        'note': f'{start} 以後下市的股票要有價格；股票池 {n_all} 檔、在市 {n_active}'})

            cur.execute("SELECT count(DISTINCT trade_date), min(trade_date), max(trade_date), count(*) FROM market_daily_prices WHERE trade_date >= %s", (start,))
            n_days, d_min, d_max, n_rows = cur.fetchone()
            cal = [d for d in trading_days(start, d_max or start)] if d_max else []
            out.append({'check': 'day_coverage', 'value': f'{n_days}/{len(cal)}',
                        'ok': bool(cal) and n_days >= 0.99 * len(cal),
                        'note': f'{d_min} ~ {d_max}，{n_rows:,} 列；交易日曆的開市日要幾乎都有資料'})

            cur.execute("SELECT count(*) FROM market_daily_prices WHERE trade_date >= %s AND adj_close IS NULL", (start,))
            n_null = cur.fetchone()[0]
            out.append({'check': 'adj_close_null', 'value': n_null, 'ok': n_null == 0,
                        'note': '報酬用 adj_close；NULL 列在回測裡等於不存在，要跑 --rebuild-adj'})

            cur.execute("""SELECT count(*) FROM market_daily_prices m
                           JOIN stock_daily_prices s USING (stock_id, trade_date)
                           WHERE m.trade_date >= %s AND abs(m.close_price - s.close_price) > 0.011""", (start,))
            n_diff = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM market_daily_prices m JOIN stock_daily_prices s USING (stock_id, trade_date) WHERE m.trade_date >= %s", (start,))
            n_cmp = cur.fetchone()[0]
            out.append({'check': 'tracked_consistency', 'value': f'{n_diff} 列不一致 / {n_cmp:,} 列比對',
                        'ok': (n_diff == 0) if n_cmp else None,
                        'note': '與追蹤股表（FinMind）同日收盤要一樣——兩個來源可混用的證據'})

            cur.execute("""WITH x AS (
                             SELECT stock_id, trade_date, high_price, low_price, close_price,
                                    lag(close_price) OVER (PARTITION BY stock_id ORDER BY trade_date) AS prev
                             FROM market_daily_prices WHERE trade_date >= %s)
                           SELECT count(*) FILTER (WHERE high_price = low_price AND prev > 0 AND abs(close_price / prev - 1) >= 0.095), count(*)
                           FROM x""", (start,))
            n_lock, n_tot = cur.fetchone()
            out.append({'check': 'limit_lock_share', 'value': f'{(n_lock / n_tot * 100) if n_tot else 0:.2f}%',
                        'ok': None, 'note': f'一字漲跌停 {n_lock:,} 列；回測要把這些日子的單視為未成交'})

            rev_start = date(start.year - 2, start.month, 1)
            cur.execute("""SELECT COALESCE(announce_source, 'none'), count(*) FROM stock_revenue_announce r
                           JOIN market_universe u USING (stock_id) WHERE r.revenue_month >= %s GROUP BY 1""", (rev_start,))
            by_src = dict(cur.fetchall())
            precise = sum(v for k, v in by_src.items() if k in ('mops_item', 'cnyes_item', 'news_item', 'finmind'))
            total = sum(by_src.values())
            cur.execute("SELECT count(DISTINCT stock_id) FROM stock_revenue_announce r JOIN market_universe u USING (stock_id) WHERE r.revenue_month >= %s", (rev_start,))
            n_rev_stocks = cur.fetchone()[0]
            out.append({'check': 'revenue_coverage', 'value': f'{n_rev_stocks}/{n_active} 檔有月營收；公告日精確 {precise:,}/{total:,}',
                        'ok': None, 'note': f'來源分布 {by_src}；AR₀ 訊號只能用公告日精確的月份'})

            cur.execute("SELECT symbol, count(*), min(trade_date), max(trade_date) FROM index_daily_prices WHERE symbol IN (%s, %s) GROUP BY 1", (TAIEX_TR, TAIEX))
            idx = {r[0]: r[1:] for r in cur.fetchall()}
            tr = idx.get(TAIEX_TR)
            out.append({'check': 'benchmark_index', 'value': f'{TAIEX_TR}: {tr[0] if tr else 0} 日（{tr[1] if tr else None} ~ {tr[2] if tr else None}）',
                        'ok': bool(tr) and tr[1] <= start + timedelta(days=10) and tr[2] >= (d_max or start),
                        'note': '含息大盤要涵蓋整段回測期'})
    return out


def status() -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT count(DISTINCT stock_id), count(*), min(trade_date), max(trade_date),
                                  count(*) FILTER (WHERE adj_close IS NULL), count(DISTINCT trade_date)
                           FROM market_daily_prices""")
            n_s, n, d0, d1, n_null, n_days = cur.fetchone()
    pend = len(pending_ids())
    return (f'market_daily_prices：{n_s} 檔、{n:,} 列、{n_days} 個交易日、{d0} ~ {d1}，adj_close NULL {n_null:,}；'
            f'還沒補完 {pend} 檔')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--backfill', action='store_true')
    ap.add_argument('--source', choices=['finmind', 'exchange'], default='finmind')
    ap.add_argument('--events', action='store_true')
    ap.add_argument('--index', action='store_true')
    ap.add_argument('--rebuild-adj', action='store_true')
    ap.add_argument('--update', action='store_true')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--start', default=PRICE_START.isoformat())
    ap.add_argument('--end', default=None)
    ap.add_argument('--date', default=None)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--retry-wait', type=int, default=600)
    ap.add_argument('--delay', type=float, default=None)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    start = date.fromisoformat(a.start)
    end = date.fromisoformat(a.end) if a.end else None

    if a.backfill:
        if a.source == 'finmind':
            print(backfill_finmind(start=start, retry_wait=a.retry_wait, delay=a.delay or FINMIND_DELAY, limit=a.limit))
        else:
            print(backfill_exchange(start=start, end=end, delay=a.delay or EXCHANGE_DELAY, limit=a.limit))
    if a.events:
        r = refresh_events(start, end, delay=a.delay or EXCHANGE_DELAY)
        print({k: (len(v) if k == 'stock_ids' else v) for k, v in r.items()})
    if a.index:
        print('index rows', backfill_index(start))
    if a.rebuild_adj:
        print('adj rows', rebuild_adj())
    if a.update:
        d = date.fromisoformat(a.date) if a.date else date.today()
        print(update_day(d))
    if a.check:
        for c in checks(start):
            flag = '✔' if c['ok'] else ('✘' if c['ok'] is False else '·')
            print(f"{flag} {c['check']:<22} {c['value']}   {c['note']}")
    if a.status or a.backfill or a.update:
        print(status())


if __name__ == '__main__':
    main()
