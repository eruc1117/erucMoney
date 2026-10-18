"""
追蹤股三張表從全市場交易所表補齊（Iteration 83）
────────────────────────────────────────────────
為什麼：`scheduler.job_stock` 每天 18:00 逐檔打 FinMind（行情、籌碼、外資持股各 1 次；Iteration 83 起除權息／減資不再打）。
追蹤股從 26 檔擴到 68 檔（0050 成分股全部）後一天 204 次呼叫；文件寫匿名 30 次／小時，130 次／天的排程一直成功、204 次沒試過——
這裡是保險（scheduler.log 裡的「Requests reach the upper limit」全是 pytest 的假 FinMind 寫進去的，排程沒撞過）。
全市場表 18:30（日線）、18:35（法人）、18:41（外資持股）已由交易所官方檔更新，一天幾次呼叫就是全市場，
而且和 FinMind 同日同值（Iteration 83 對照 `tracked-sync-compare-83`：2018 起兩表共有的股票日，收盤與開高低 100% 相同、
漲跌有值的列 100% 相同；法人三欄、外資持股股數與發行股數逐列相同。只有上櫃的 5483 成交量 FinMind 比櫃買檔多——
櫃買檔的成交量不含零股與盤後；上市股全同。交易所檔在部分日子漲跌是 NULL（檔裡印 X），補列時用前一日收盤算回來）。
所以 18:43 把追蹤股缺的列從全市場表補進去；FinMind 已寫的列不覆蓋（ON CONFLICT DO NOTHING）。

補進 stock_daily_prices 的列 adj_close 是 NULL，和 FinMind 路徑一樣要重建（Iteration 18 起算報酬一律用 adj_close），
事件表 stock_dividend_result／stock_capital_reduction 由 job_market_daily（18:30）用交易所檔維護，不用再打 FinMind；
所以除了補到行情列的股票，自 since 起有公司行動的追蹤股也重建一次（job_stock 18:00 重建時 18:30 的新事件還沒進表）。

用法（Crawler 目錄）：
    python tracked_sync.py                       # 全部追蹤股，近 7 天
    python tracked_sync.py --since 2018-01-01    # 補整段（新加入追蹤股用）
    python tracked_sync.py --stocks 2454 2308
"""

import argparse
import logging
from datetime import date, timedelta

from db.connection import get_conn

logger = logging.getLogger(__name__)

DEFAULT_DAYS = 7      # 排程每天補近 7 天：涵蓋連假與補班，和 job_stock 的窗口一樣

PRICES_SQL = """
    WITH m AS (
        SELECT stock_id, trade_date, open_price, high_price, low_price, close_price,
               volume, turnover_value, transaction_count,
               COALESCE(change_value,
                        close_price - lag(close_price) OVER (PARTITION BY stock_id ORDER BY trade_date)) AS change_value
        FROM market_daily_prices
        WHERE stock_id = ANY(%s) AND trade_date >= %s - INTERVAL '20 days' AND close_price > 0)
    INSERT INTO stock_daily_prices
        (stock_id, trade_date, open_price, high_price, low_price, close_price,
         volume, turnover_value, transaction_count, change_value, change_rate)
    SELECT stock_id, trade_date, open_price, high_price, low_price, close_price,
           volume, turnover_value, transaction_count, change_value,
           CASE WHEN change_value IS NOT NULL AND close_price - change_value <> 0
                THEN round(change_value / (close_price - change_value) * 100, 3) END
    FROM m
    WHERE trade_date >= %s
    ON CONFLICT (stock_id, trade_date) DO NOTHING
    RETURNING stock_id
"""

CHIPS_SQL = """
    INSERT INTO stock_chip_analysis
        (stock_id, trade_date, foreign_investor_buy, investment_trust_buy, dealer_buy, total_net_buy)
    SELECT stock_id, trade_date, foreign_net, trust_net, dealer_net, total_net
    FROM market_institutional_daily
    WHERE stock_id = ANY(%s) AND trade_date >= %s
    ON CONFLICT (stock_id, trade_date) DO NOTHING
"""

HOLDING_SQL = """
    INSERT INTO stock_foreign_holding
        (stock_id, trade_date, foreign_shares, foreign_ratio, shares_issued)
    SELECT stock_id, trade_date, foreign_shares, foreign_ratio, shares_issued
    FROM market_foreign_holding_daily
    WHERE stock_id = ANY(%s) AND trade_date >= %s
    ON CONFLICT (stock_id, trade_date) DO NOTHING
"""


def tracked_ids() -> list[str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stock_id FROM stock_info WHERE is_tracking = TRUE ORDER BY stock_id")
            return [r[0] for r in cur.fetchall()]


def fill_from_market(ids: list[str] | None = None, since: date | None = None, rebuild: bool = True) -> dict:
    """把 ids（預設全部追蹤股）自 since（預設 7 天前）起缺的列從全市場表補進三張追蹤股表。
    回傳 {'prices', 'chips', 'holding', 'rebuilt', 'stock_ids'}；stock_ids 是要重建 adj_close 的股票：補到行情列的，加上自 since 起有除權息／減資事件的。"""
    ids = list(ids) if ids is not None else tracked_ids()
    since = since or (date.today() - timedelta(days=DEFAULT_DAYS))
    out = {'prices': 0, 'chips': 0, 'holding': 0, 'rebuilt': 0, 'stock_ids': []}
    if not ids:
        return out
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(PRICES_SQL, (ids, since, since))
            touched = sorted({r[0] for r in cur.fetchall()})
            out['prices'] = cur.rowcount
            cur.execute(CHIPS_SQL, (ids, since))
            out['chips'] = cur.rowcount
            cur.execute(HOLDING_SQL, (ids, since))
            out['holding'] = cur.rowcount
            cur.execute("""SELECT stock_id FROM stock_dividend_result WHERE stock_id = ANY(%s) AND ex_date >= %s
                           UNION SELECT stock_id FROM stock_capital_reduction WHERE stock_id = ANY(%s) AND ex_date >= %s""",
                        (ids, since, ids, since))
            touched = sorted(set(touched) | {r[0] for r in cur.fetchall()})
        conn.commit()
    out['stock_ids'] = touched
    if rebuild and touched:
        import rebuild_adj_close
        out['rebuilt'] = rebuild_adj_close.rebuild(touched)
    logger.info("[tracked_sync] %d 檔自 %s：行情 +%d、籌碼 +%d、外資持股 +%d，重建 adj_close %d 檔 %d 列",
                len(ids), since, out['prices'], out['chips'], out['holding'], len(touched), out['rebuilt'])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', default=None, help='起日 YYYY-MM-DD（預設 7 天前）')
    ap.add_argument('--stocks', nargs='+', default=None)
    ap.add_argument('--no-rebuild', action='store_true', help='不重建 adj_close（只補列）')
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    since = date.fromisoformat(args.since) if args.since else None
    r = fill_from_market(args.stocks, since, rebuild=not args.no_rebuild)
    print(r)


if __name__ == '__main__':
    main()
