"""
資料新鮮度檢查與自動補齊（Iteration 27）
────────────────────────────────────────
需求：服務重啟時，檢查「預測比對」裡那些股票的行情有沒有到最新，沒有就自動補齊。

## 為什麼要有這個

預測比對要能運作，前提是**目標日期的收盤價已經進資料庫**。
少了那幾天，比對就永遠停在「尚未到期」——而畫面上看不出是「還沒到那天」
還是「到了但沒抓」。這兩件事對使用者的意義完全不同：前者只能等，
後者按一下就能解決。

## 「最新」怎麼定義

沒有一份可靠的台股交易日曆可用（國定假日不固定），所以不猜哪天該開盤，
改用資料本身當基準：

    市場基準日 = 全體股票 max(trade_date)

某檔的最後交易日**早於**市場基準日，就代表它落後——
因為同一天其他股票有資料，它沒有。這個判準不需要任何日曆知識，
也不會在連假期間誤判整批股票落後。

另外會回報市場基準日距今幾個日曆天。若超過門檻，那是排程沒跑的問題，
不是個股落後的問題——兩者要分開講，否則使用者會以為按了補齊就能解決。

## FinMind 額度是硬限制

匿名額度 30 次/小時（`config.py` 的 token 目前為空）。
每檔股票補一次行情就是一次呼叫，所以：

  · 一次最多補 `MAX_PER_RUN` 檔，超過的留給下一輪
  · 啟動時的自動補齊預設**只補「預測比對」與「持股」用到的股票**，
    不是全部追蹤清單——那些有排程在顧
  · 補完會回報剩下幾檔沒補，不會假裝全部完成
"""

import logging
import threading
from datetime import date

logger = logging.getLogger(__name__)

MAX_PER_RUN = 8          # 單次自動補齊的股票數上限（受 FinMind 匿名額度限制）
STALE_MARKET_DAYS = 4    # 市場基準日距今超過這麼多天，視為排程可能沒跑

_state = {'running': False, 'last': None}


def _relevant_stock_ids() -> list:
    """
    需要保持最新的股票：預測比對用到的 + 使用者持股。

    不含全部追蹤清單——那些有每日排程在顧，塞進來只會白白吃掉 API 額度。
    """
    from db.connection import get_conn
    # 只取台股（market = 'tw'）：美股的 LSTM 預測也存在 saved_predictions，
    # 混進來會把 TSM 這種美股代號拿去 FinMind 台股資料集查，永遠「落後 8000 多天」，
    # 而且每輪補齊都白白吃一次額度（Iteration 35 修正）。
    sql = """
        SELECT DISTINCT stock_id FROM saved_predictions WHERE COALESCE(market, 'tw') = 'tw'
        UNION
        SELECT DISTINCT stock_id FROM user_holdings
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                return sorted(r[0] for r in cur.fetchall())
    except Exception as e:
        logger.warning('[freshness] 取得相關股票失敗：%s', e)
        return []


def check(stock_ids: list = None) -> dict:
    """
    回報每檔的最後交易日與落後天數。不做任何寫入。

    落後天數用「市場上有幾個交易日、這檔沒有」計算，
    不是日曆天差——連假期間用日曆天會把所有股票都算成落後。
    """
    from db.connection import get_conn

    ids = stock_ids if stock_ids is not None else _relevant_stock_ids()
    if not ids:
        return {'available': True, 'market_last': None, 'items': [],
                'stale': [], 'note': '沒有需要檢查的股票（預測比對與持股都是空的）'}

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT max(trade_date) FROM stock_daily_prices')
                market_last = cur.fetchone()[0]
                if market_last is None:
                    return {'available': False, 'reason': '資料庫裡沒有任何行情資料'}

                cur.execute("""
                    SELECT s.stock_id,
                           max(p.trade_date) AS last_date,
                           count(p.*)        AS rows,
                           (SELECT count(DISTINCT trade_date) FROM stock_daily_prices
                             WHERE trade_date > COALESCE(max(p.trade_date), DATE '1900-01-01')) AS behind
                      FROM unnest(%s::text[]) AS s(stock_id)
                      LEFT JOIN stock_daily_prices p ON p.stock_id = s.stock_id
                     GROUP BY s.stock_id
                     ORDER BY s.stock_id
                """, (ids,))
                rows = cur.fetchall()
    except Exception as e:
        logger.warning('[freshness] 檢查失敗：%s', e)
        return {'available': False, 'reason': str(e)[:160]}

    items = []
    for sid, last_date, n, behind in rows:
        items.append({
            'stock_id': sid,
            'last_date': last_date.isoformat() if last_date else None,
            'rows': int(n or 0),
            'days_behind': int(behind or 0),
            'stale': bool(behind and behind > 0) or not last_date,
        })

    market_gap = (date.today() - market_last).days
    return {
        'available': True,
        'market_last': market_last.isoformat(),
        'market_gap_days': market_gap,
        'market_stale': market_gap > STALE_MARKET_DAYS,
        'items': items,
        'stale': [i for i in items if i['stale']],
        'note': ('落後＝市場上有交易日、這檔沒有；不用日曆天判斷，'
                 '否則連假期間會把所有股票都算成落後。'
                 + (f'　另外市場基準日距今 {market_gap} 天，'
                    '若持續擴大是排程沒跑，不是個股落後。'
                    if market_gap > STALE_MARKET_DAYS else '')),
    }


def backfill(stock_ids: list = None, max_stocks: int = MAX_PER_RUN) -> dict:
    """
    把落後的股票補到最新。回傳實際補了哪些、剩下幾檔沒補。

    受 FinMind 匿名額度（30 次/小時）限制，一次只補 max_stocks 檔；
    沒補完會照實回報，不假裝完成。
    """
    from datetime import timedelta
    from db.repository import upsert_daily_prices, upsert_chip_analysis, upsert_foreign_holding
    from scrapers.finmind_scraper import FinMindScraper

    status = check(stock_ids)
    if not status.get('available'):
        return {'ok': False, 'reason': status.get('reason', '檢查失敗')}

    stale = status['stale']
    if not stale:
        return {'ok': True, 'filled': [], 'remaining': 0,
                'reason': '所有相關股票的行情都已是最新'}

    targets = stale[:max_stocks]
    today = date.today()
    filled, failed = [], []

    for item in targets:
        sid = item['stock_id']
        # 從該檔最後一天的隔天開始補；完全沒資料的就抓近三個月
        start = (date.fromisoformat(item['last_date']) + timedelta(days=1)
                 if item['last_date'] else today - timedelta(days=90))
        try:
            scraper = FinMindScraper(stock_ids=[sid], start_date=start, end_date=today)
            prices = scraper.fetch_prices()
            n = upsert_daily_prices([p for p in prices if p])
            c = h = 0
            try:
                c = upsert_chip_analysis(scraper.fetch_chips())
            except Exception:
                pass          # 籌碼失敗不影響行情，且會多吃一次額度
            try:
                h = upsert_foreign_holding(scraper.fetch_foreign_holding())
            except Exception:
                pass          # 外資持股同上（Iteration 35）
            filled.append({'stock_id': sid, 'from': start.isoformat(),
                           'prices': n, 'chips': c, 'holding': h})
            logger.info('[freshness] %s 補齊 %s ~ %s：行情 %d 筆、籌碼 %d 筆、外資持股 %d 筆',
                        sid, start, today, n, c, h)
        except Exception as e:
            failed.append({'stock_id': sid, 'error': str(e)[:120]})
            logger.warning('[freshness] %s 補齊失敗：%s', sid, e)

    # 補完把面板快取清掉，否則推論還是拿到舊資料
    try:
        import panel_cache
        panel_cache.invalidate()
    except Exception:
        pass

    return {
        'ok': True,
        'filled': filled,
        'failed': failed,
        'remaining': max(len(stale) - len(targets), 0),
        'reason': (f'補齊 {len(filled)} 檔'
                   + (f'，{len(failed)} 檔失敗' if failed else '')
                   + (f'，尚有 {len(stale) - len(targets)} 檔待補'
                      '（FinMind 匿名額度 30 次/小時，留給下一輪）'
                      if len(stale) > len(targets) else '')),
    }


# ── 外生資料表（Iteration 32）────────────────────────────────────────────────
# 美股、台指期、韓日指數。它們與台股行情有一個關鍵差別：**沒有任何排程在顧**，
# 直到 Iteration 32 才補上。落後的症狀也不同——跳空模型照樣會輸出預測，
# 只是用的是三天前的美股，畫面上完全看不出來。
EXOGENOUS = {
    'us': {
        'label': '美股行情', 'table': 'us_daily_prices', 'date_col': 'trade_date',
        'stale_days': 4,        # 週末＋一天國定假日
        'note': '跳空模型（台股）與美股跳空模型都靠它',
    },
    'futures': {
        'label': '台指期', 'table': 'futures_daily', 'date_col': 'trade_date',
        'stale_days': 4,
        'note': '夜盤是台股跳空模型最強的單一特徵',
    },
    'index': {
        'label': '韓日指數', 'table': 'index_daily_prices', 'date_col': 'trade_date',
        'stale_days': 4,
        'note': '振幅模型與美股跳空模型使用',
    },
}


def check_exogenous() -> dict:
    """
    外生資料表的最新日期與落後天數。

    這裡只能用日曆天判斷（沒有「其他標的今天有資料」可以當基準，
    整張表就是同一個市場），所以門檻放寬到 4 天涵蓋週末與國定假日；
    真正的用途是抓「排程沒跑」這種持續擴大的落後，不是精準抓單日。
    """
    from db.connection import get_conn
    out, problems = [], []
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                for key, meta in EXOGENOUS.items():
                    cur.execute(f"SELECT max({meta['date_col']}) FROM {meta['table']}")
                    last = cur.fetchone()[0]
                    gap = (date.today() - last).days if last else None
                    stale = last is None or gap > meta['stale_days']
                    out.append({'key': key, 'label': meta['label'],
                                'table': meta['table'],
                                'last_date': last.isoformat() if last else None,
                                'days_behind': gap, 'stale': stale,
                                'note': meta['note']})
                    if stale:
                        problems.append(f"{meta['label']}落後 {gap} 天"
                                        f"（最新 {last}）" if last else
                                        f"{meta['label']}沒有任何資料")
    except Exception as e:
        logger.warning('[freshness] 外生資料檢查失敗：%s', e)
        return {'available': False, 'reason': str(e)[:160]}
    return {'available': True, 'items': out, 'problems': problems}


def refill_exogenous(days: int = 30) -> dict:
    """
    把外生資料補到最新。排程與手動補齊共用這一條路徑。

    三個來源分開 try：yfinance（韓日）掛掉不該讓 FinMind（美股、期貨）也不跑。
    美股 23 檔 ＝ 23 次 FinMind 呼叫，期貨 2 次；匿名額度 30 次/小時，
    所以這個組合一小時跑一次是安全的，`retry_wait=0` 讓額度用完時直接放棄本輪。
    """
    from datetime import timedelta
    start = date.today() - timedelta(days=days)
    res = {}

    try:
        import backfill_us
        res['us'] = backfill_us.run(start=start, retry_wait=0, pause=1.0)
    except Exception as e:
        res['us'] = {'error': str(e)[:160]}
        logger.warning('[freshness] 美股回補失敗：%s', e)

    try:
        import backfill_futures
        res['futures'] = backfill_futures.backfill(
            backfill_futures.DEFAULT_IDS, start, date.today(), pause=1.0)
    except Exception as e:
        res['futures'] = {'error': str(e)[:160]}
        logger.warning('[freshness] 期貨回補失敗：%s', e)

    try:
        import backfill_index
        res['index'] = backfill_index.run(start=start)
    except Exception as e:
        res['index'] = {'error': str(e)[:160]}
        logger.warning('[freshness] 韓日指數回補失敗：%s', e)

    # 補完要清面板快取，否則推論還是拿到舊資料（與台股補齊同樣的坑）
    try:
        import panel_cache
        panel_cache.invalidate()
    except Exception:
        pass
    return res


def run_startup_check(auto_fill: bool = True) -> None:
    """
    服務啟動時在背景跑一次：檢查 →（需要時）補齊。

    刻意放在背景執行緒：補資料會打外部 API，讓它擋住服務啟動是不對的，
    使用者會以為服務掛了。
    """
    if _state['running']:
        return

    def _work():
        _state['running'] = True
        try:
            status = check()
            if not status.get('available'):
                logger.warning('[freshness] 啟動檢查失敗：%s', status.get('reason'))
                return
            stale = status.get('stale', [])
            logger.info('[freshness] 啟動檢查：市場基準日 %s，相關股票 %d 檔，落後 %d 檔',
                        status['market_last'], len(status['items']), len(stale))
            if status.get('market_stale'):
                logger.warning('[freshness] 市場基準日距今 %d 天——'
                               '這是排程沒跑，不是個股落後',
                               status['market_gap_days'])
            if stale and auto_fill:
                logger.info('[freshness] 自動補齊：%s',
                            '、'.join(i['stock_id'] for i in stale[:MAX_PER_RUN]))
                _state['last'] = backfill()
                logger.info('[freshness] %s', _state['last'].get('reason'))
            else:
                _state['last'] = {'ok': True, 'filled': [], 'remaining': len(stale),
                                  'reason': '無需補齊' if not stale else '已停用自動補齊'}
        except Exception as e:
            logger.warning('[freshness] 啟動檢查例外：%s', e)
        finally:
            _state['running'] = False

    threading.Thread(target=_work, daemon=True, name='freshness-startup').start()


def last_result() -> dict:
    return {'running': _state['running'], 'last': _state['last']}
