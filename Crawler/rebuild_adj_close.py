"""
建立還原權值收盤價 adj_close（Iteration 18）
────────────────────────────────────────────
把「除權息 + 減資」的機械性價格缺口一次還原到欄位裡，
讓任何地方「用 adj_close 算報酬」都自動正確，不必各處記得做調整。

## 演算法（回溯還原，back-adjustment）

對每個公司行動（除權息或減資）：

    factor = 參考價 ÷ 事件前收盤

    · 除權息：參考價 < 前收（配息發出去）→ factor < 1
    · 減資  ：參考價 > 前收（股份註銷）  → factor > 1

    adj_close[t] = close[t] × ∏(factor for every event with ex_date > t)

亦即把事件**之前**的歷史價格按比例縮放，使跨越事件的報酬率連續。
最新一段永遠等於原始收盤（累積 factor = 1），故 adj_close 的最新值
與 close 相同，方便對帳。

## 用法

    python rebuild_adj_close.py                 # 回補減資資料 + 重建全部 adj_close
    python rebuild_adj_close.py --skip-fetch    # 只重建（不呼叫 API）
    python rebuild_adj_close.py --stocks 2409   # 限定股票
"""

import argparse
import logging
import time
from datetime import date

from db.connection import get_conn
from scrapers.finmind_scraper import FinMindScraper

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def tracked_ids() -> list[str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT stock_id FROM stock_daily_prices "
                        "ORDER BY stock_id")
            return [r[0] for r in cur.fetchall()]


def fetch_reductions(ids: list, start: date, retry_wait: int = 300) -> int:
    total = 0
    for i, sid in enumerate(ids, 1):
        attempts = 0
        while True:
            attempts += 1
            try:
                sc = FinMindScraper(stock_ids=[sid], start_date=start,
                                    end_date=date.today())
                rows = sc.fetch_capital_reductions()
                if rows:
                    with get_conn() as conn:
                        with conn.cursor() as cur:
                            for r in rows:
                                cur.execute("""
                                    INSERT INTO stock_capital_reduction
                                        (stock_id, ex_date, before_price,
                                         reference_price, reason)
                                    VALUES (%s,%s,%s,%s,%s)
                                    ON CONFLICT (stock_id, ex_date) DO UPDATE SET
                                        before_price    = EXCLUDED.before_price,
                                        reference_price = EXCLUDED.reference_price,
                                        reason          = EXCLUDED.reason
                                """, (r['stock_id'], r['ex_date'], r['before_price'],
                                      r['reference_price'], r['reason']))
                        conn.commit()
                    total += len(rows)
                    logger.info("[%d/%d] %s 減資 %d 筆", i, len(ids), sid, len(rows))
                break
            except Exception as e:
                if retry_wait > 0 and attempts <= 6:
                    logger.warning("[%d/%d] %s 失敗（%s），%d 秒後重試",
                                   i, len(ids), sid, e, retry_wait)
                    time.sleep(retry_wait)
                    continue
                logger.error("[%d/%d] %s 放棄：%s", i, len(ids), sid, e)
                break
        time.sleep(2)
    return total


def load_events(stock_ids: list) -> dict:
    """
    彙整每檔的公司行動 {stock_id: [(ex_date, factor), ...]}。
    factor 只在 (0, 5) 的合理範圍內採用，避免資料異常造成價格失真。
    """
    sql_div = """
        SELECT stock_id, ex_date, before_price, reference_price
        FROM stock_dividend_result
        WHERE reference_price > 0 AND before_price > 0
    """
    sql_red = """
        SELECT stock_id, ex_date, before_price, reference_price
        FROM stock_capital_reduction
        WHERE reference_price > 0 AND before_price > 0
    """
    events, skipped = {}, 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for sql, kind in ((sql_div, '除權息'), (sql_red, '減資')):
                cur.execute(sql)
                for sid, ex_date, before, ref in cur.fetchall():
                    if sid not in stock_ids:
                        continue
                    factor = float(ref) / float(before)
                    if not (0.2 < factor < 5.0):
                        skipped += 1
                        logger.warning('略過異常 factor：%s %s %s→%s（%.3f）',
                                       sid, ex_date, before, ref, factor)
                        continue
                    events.setdefault(sid, []).append((ex_date, factor, kind))
    for sid in events:
        events[sid].sort(key=lambda x: x[0])
    n = sum(len(v) for v in events.values())
    logger.info("公司行動共 %d 筆（%d 檔），略過異常 %d 筆", n, len(events), skipped)
    return events


def rebuild(stock_ids: list) -> int:
    """重算 adj_close 並寫回。"""
    events = load_events(set(stock_ids))
    updated = 0

    for sid in stock_ids:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT trade_date, close_price FROM stock_daily_prices
                    WHERE stock_id = %s AND close_price > 0
                    ORDER BY trade_date
                """, (sid,))
                rows = cur.fetchall()
        if not rows:
            continue

        evs = events.get(sid, [])
        # 由最新往回累乘：某日的調整係數 = 其後所有事件 factor 的乘積
        cum, cum_map = 1.0, {}
        ev_idx = len(evs) - 1
        for trade_date, close in reversed(rows):
            while ev_idx >= 0 and evs[ev_idx][0] > trade_date:
                cum *= evs[ev_idx][1]
                ev_idx -= 1
            cum_map[trade_date] = cum

        with get_conn() as conn:
            with conn.cursor() as cur:
                for trade_date, close in rows:
                    adj = float(close) * cum_map[trade_date]
                    cur.execute("""
                        UPDATE stock_daily_prices SET adj_close = %s
                        WHERE stock_id = %s AND trade_date = %s
                    """, (round(adj, 4), sid, trade_date))
                    updated += 1
            conn.commit()
        if evs:
            logger.info("%s：%d 筆行情，%d 個公司行動，最早調整係數 %.4f",
                        sid, len(rows), len(evs), cum_map[rows[0][0]])
    return updated


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stocks', nargs='+', default=None)
    ap.add_argument('--skip-fetch', action='store_true', help='不呼叫 API，只重建')
    ap.add_argument('--start', default='1990-01-01')
    args = ap.parse_args()

    ids = args.stocks or tracked_ids()
    if not args.skip_fetch:
        logger.info("回補減資資料 %d 檔…", len(ids))
        n = fetch_reductions(ids, date.fromisoformat(args.start))
        logger.info("減資資料共 %d 筆", n)

    logger.info("重建 adj_close…")
    updated = rebuild(ids)
    logger.info("完成：更新 %d 筆 adj_close", updated)


if __name__ == "__main__":
    main()
