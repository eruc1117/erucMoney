"""
FastAPI 伺服器
提供前端 (Screen) 所需的股票資料 API。

啟動方式：
  python main.py --mode server
  # 或直接：
  uvicorn api:app --host 0.0.0.0 --port 8000 --reload
"""

import logging
import threading
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from db.connection import get_conn

logger = logging.getLogger(__name__)

app = FastAPI(title="Stock API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 個股基本資訊 + 最新行情 ────────────────────────────────────────────────
# GET /stocks/{stock_id}
# Response: { stock_id, stock_name, market_type, industry_type,
#             close_price, change_value, change_rate, volume,
#             turnover_value, total_net_buy, foreign_holding_ratio }
@app.get("/stocks/{stock_id}")
def get_stock(stock_id: str):
    sql = """
        SELECT
            i.stock_id, i.stock_name, i.market_type, i.industry_type,
            p.close_price, p.change_value, p.change_rate,
            p.volume, p.turnover_value,
            c.total_net_buy, c.foreign_holding_ratio
        FROM stock_info i
        LEFT JOIN LATERAL (
            SELECT close_price, change_value, change_rate, volume, turnover_value
            FROM stock_daily_prices
            WHERE stock_id = i.stock_id
            ORDER BY trade_date DESC
            LIMIT 1
        ) p ON TRUE
        LEFT JOIN LATERAL (
            SELECT total_net_buy, foreign_holding_ratio
            FROM stock_chip_analysis
            WHERE stock_id = i.stock_id
            ORDER BY trade_date DESC
            LIMIT 1
        ) c ON TRUE
        WHERE i.stock_id = %s
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (stock_id,))
            row = cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="股票不存在")

    keys = [
        "stock_id", "stock_name", "market_type", "industry_type",
        "close_price", "change_value", "change_rate",
        "volume", "turnover_value",
        "total_net_buy", "foreign_holding_ratio",
    ]
    return dict(zip(keys, row))


# ── 依預算篩選股票 ──────────────────────────────────────────────────────────
# GET /stocks?max_price={maxPrice}
# Response: [{ stock_id, stock_name, close_price, change_rate, volume }, ...]
@app.get("/stocks")
def get_stocks_by_budget(max_price: float = Query(..., gt=0)):
    sql = """
        SELECT
            i.stock_id, i.stock_name,
            p.close_price, p.change_rate, p.volume
        FROM stock_info i
        JOIN LATERAL (
            SELECT close_price, change_rate, volume
            FROM stock_daily_prices
            WHERE stock_id = i.stock_id
              AND close_price IS NOT NULL
            ORDER BY trade_date DESC
            LIMIT 1
        ) p ON p.close_price <= %s
        ORDER BY p.close_price DESC
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (max_price,))
            rows = cur.fetchall()

    keys = ["stock_id", "stock_name", "close_price", "change_rate", "volume"]
    return [dict(zip(keys, r)) for r in rows]


# ── 每日行情（K線）────────────────────────────────────────────────────────
# GET /stocks/{stock_id}/prices?days={days}
# Response: [{ trade_date, open_price, high_price, low_price,
#              close_price, volume, change_rate }, ...]
@app.get("/stocks/{stock_id}/prices")
def get_stock_prices(stock_id: str, days: int = Query(90, ge=1, le=365)):
    sql = """
        SELECT trade_date, open_price, high_price, low_price,
               close_price, volume, change_rate
        FROM stock_daily_prices
        WHERE stock_id = %s
          AND trade_date >= CURRENT_DATE - %s
        ORDER BY trade_date ASC
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (stock_id, days))
            rows = cur.fetchall()

    keys = ["trade_date", "open_price", "high_price", "low_price",
            "close_price", "volume", "change_rate"]
    return [
        {**dict(zip(keys, r)), "trade_date": r[0].isoformat()}
        for r in rows
    ]


# ── 三大法人籌碼 ──────────────────────────────────────────────────────────
# GET /stocks/{stock_id}/chips?days={days}
# Response: [{ trade_date, foreign_investor_buy, investment_trust_buy,
#              dealer_buy, total_net_buy }, ...]
@app.get("/stocks/{stock_id}/chips")
def get_chip_data(stock_id: str, days: int = Query(20, ge=1, le=365)):
    sql = """
        SELECT trade_date, foreign_investor_buy, investment_trust_buy,
               dealer_buy, total_net_buy
        FROM stock_chip_analysis
        WHERE stock_id = %s
          AND trade_date >= CURRENT_DATE - %s
        ORDER BY trade_date ASC
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (stock_id, days))
            rows = cur.fetchall()

    keys = ["trade_date", "foreign_investor_buy", "investment_trust_buy",
            "dealer_buy", "total_net_buy"]
    return [
        {**dict(zip(keys, r)), "trade_date": r[0].isoformat()}
        for r in rows
    ]


# ── 觸發爬蟲 ──────────────────────────────────────────────────────────────
# POST /crawler/run  Body: { stock_id }
# Response: { status: "started" | "already_running", task_id }

_running_tasks: set[str] = set()
_tasks_lock    = threading.Lock()

# ── 爬蟲冷卻：同一股票 30 分鐘內只允許執行一次 ────────────────────────────
CRAWL_COOLDOWN_SECONDS = 1800   # 30 分鐘
_crawl_done_at: dict[str, datetime] = {}
_cooldown_lock = threading.Lock()


HIST_MAX_DAYS = 365   # 單次歷史補充上限


class CrawlerRequest(BaseModel):
    stock_id:   str
    start_date: Optional[str] = None   # YYYY-MM-DD，歷史補充起始日
    end_date:   Optional[str] = None   # YYYY-MM-DD，歷史補充結束日


def _run_crawler(stock_id: str,
                 start_date_str: Optional[str] = None,
                 end_date_str:   Optional[str] = None):
    from scrapers.finmind_scraper import FinMindScraper
    from db.repository import upsert_daily_prices, upsert_chip_analysis, upsert_stock_info

    end_date   = date.fromisoformat(end_date_str)   if end_date_str   else date.today()
    start_date = date.fromisoformat(start_date_str) if start_date_str else end_date - timedelta(days=89)

    # 防呆：結束日不超過今天，範圍不超過上限
    end_date   = min(end_date, date.today())
    if (end_date - start_date).days > HIST_MAX_DAYS:
        start_date = end_date - timedelta(days=HIST_MAX_DAYS)
        logger.warning("[crawler] 日期範圍超過 %d 天，自動調整起始至 %s", HIST_MAX_DAYS, start_date)

    try:
        scraper = FinMindScraper(
            stock_ids=[stock_id],
            start_date=start_date,
            end_date=end_date,
        )

        # 個股基本資訊
        infos = scraper.fetch_stock_info()
        if infos:
            for info in infos:
                upsert_stock_info(**info)
        else:
            upsert_stock_info(stock_id, stock_id)

        # 每日行情
        prices = scraper.fetch_prices()
        price_count = upsert_daily_prices([p for p in prices if p])

        # 三大法人籌碼
        chips = scraper.fetch_chips()
        chip_count = upsert_chip_analysis(chips)

        logger.info("[crawler/run] 完成：%s 行情 %d 筆，籌碼 %d 筆",
                    stock_id, price_count, chip_count)
    except Exception as e:
        logger.error("[crawler/run] 失敗 %s: %s", stock_id, e)
    finally:
        with _tasks_lock:
            _running_tasks.discard(stock_id)
        # 只有「近期資料」模式才更新冷卻時間（歷史補充不影響冷卻）
        if not start_date_str:
            with _cooldown_lock:
                _crawl_done_at[stock_id] = datetime.now()


@app.post("/crawler/run")
def trigger_crawler(body: CrawlerRequest):
    sid          = body.stock_id.strip()
    is_historical = bool(body.start_date)   # 有指定起始日 = 歷史補充模式

    # 冷卻檢查：僅「近期資料」模式受限，歷史補充直接略過
    if not is_historical:
        with _cooldown_lock:
            last = _crawl_done_at.get(sid)
            if last:
                elapsed     = (datetime.now() - last).total_seconds()
                retry_after = int(CRAWL_COOLDOWN_SECONDS - elapsed)
                if retry_after > 0:
                    logger.info("[crawler/run] 冷卻中 %s，剩餘 %ds", sid, retry_after)
                    return {
                        "status":      "rate_limited",
                        "task_id":     sid,
                        "retry_after": retry_after,
                    }

    # 並發檢查：同一股票已在執行中 → 拒絕
    with _tasks_lock:
        if sid in _running_tasks:
            return {"status": "already_running", "task_id": sid}
        _running_tasks.add(sid)

    t = threading.Thread(
        target=_run_crawler,
        args=(sid, body.start_date, body.end_date),
        daemon=True,
    )
    t.start()
    return {"status": "started", "task_id": sid, "mode": "historical" if is_historical else "recent"}


# ── 爬蟲狀態查詢 ───────────────────────────────────────────────────────────
# GET /crawler/status/{stock_id}
# Response: { stock_id, status: "running" | "idle" }
@app.get("/crawler/status/{stock_id}")
def get_crawler_status(stock_id: str):
    with _tasks_lock:
        running = stock_id in _running_tasks
    return {"stock_id": stock_id, "status": "running" if running else "idle"}


# ── 新聞爬蟲 ──────────────────────────────────────────────────────────────
# POST /crawler/news           觸發新聞爬蟲（即時 or 指定日期範圍 Wayback）
# GET  /crawler/news/status    查詢爬蟲狀態

_news_crawl_running = False
_news_crawl_lock    = threading.Lock()
_news_crawl_count   = 0    # 最後一次爬取新增筆數
_news_crawl_mode    = ''   # 'realtime' | 'historical'


class NewsCrawlRequest(BaseModel):
    start_date: Optional[str]       = None   # YYYY-MM-DD，歷史模式起始日
    end_date:   Optional[str]       = None   # YYYY-MM-DD，歷史模式結束日
    keywords:   Optional[list[str]] = None   # 關鍵字過濾（空或 None 表示不過濾）


@app.post("/crawler/news")
def trigger_news_crawl(body: NewsCrawlRequest = NewsCrawlRequest()):
    global _news_crawl_running, _news_crawl_count, _news_crawl_mode
    with _news_crawl_lock:
        if _news_crawl_running:
            return {"status": "already_running", "mode": _news_crawl_mode}
        _news_crawl_running = True
        _news_crawl_mode    = "historical" if body.start_date else "realtime"

    start_date = body.start_date
    end_date   = body.end_date or body.start_date   # 若只填 start，則單日爬取

    kws = [k.strip() for k in (body.keywords or []) if k.strip()]

    def _run():
        global _news_crawl_running, _news_crawl_count
        try:
            from scrapers.news_scraper import NewsScraper
            from db.repository import insert_news_articles
            scraper = NewsScraper()
            if start_date:
                articles = scraper.scrape_with_date_range(start_date, end_date)
                logger.info("[crawler/news] 歷史模式 %s ~ %s", start_date, end_date)
            else:
                articles = scraper.scrape_all()
                logger.info("[crawler/news] 即時模式")
            # 關鍵字過濾（任一關鍵字出現在標題或內文即保留）
            if kws:
                kws_lower = [k.lower() for k in kws]
                articles = [
                    a for a in articles
                    if any(k in (a.get('title', '') + ' ' + a.get('content', '')).lower()
                           for k in kws_lower)
                ]
                logger.info("[crawler/news] 關鍵字過濾後 %d 則，關鍵字：%s", len(articles), kws)
            # ① 所有原始文章寫入中介表（含財金旗標）
            from db.repository import insert_raw_news_batch
            insert_raw_news_batch(articles)

            # ② 僅財金文章寫入 user_news
            fin_articles = [a for a in articles if a.get('is_financial', True)]
            count = insert_news_articles(fin_articles)
            _news_crawl_count = count
            logger.info("[crawler/news] 完成，原始 %d 則 → 財金 %d 則寫入 user_news",
                        len(articles), count)
        except Exception as e:
            logger.error("[crawler/news] 失敗: %s", e)
        finally:
            with _news_crawl_lock:
                _news_crawl_running = False

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "mode": _news_crawl_mode}


@app.get("/crawler/news/status")
def get_news_crawl_status():
    with _news_crawl_lock:
        running = _news_crawl_running
        mode    = _news_crawl_mode
    return {
        "status":     "running" if running else "idle",
        "mode":       mode,
        "last_count": _news_crawl_count,
    }


# ── 投票觸發 ──────────────────────────────────────────────────────────────────
# POST /voting/run  Body: { stock_ids: ["2303", ...] }

_vote_running = False
_vote_lock    = threading.Lock()
_vote_results: list = []

class VoteRequest(BaseModel):
    stock_ids: List[str]
    # 使用者選中的模型目錄鍵（Iteration 31）。省略＝用 model_catalog 的預設集合
    models: Optional[List[str]] = None

@app.post("/voting/run")
def trigger_vote(body: VoteRequest):
    global _vote_running, _vote_results
    with _vote_lock:
        if _vote_running:
            return {"status": "already_running"}
        _vote_running = True

    def _run():
        global _vote_running, _vote_results
        try:
            import sys, os
            sys.path.insert(0, os.path.dirname(__file__))
            from voting_engine import run_vote_batch
            _vote_results = run_vote_batch(body.stock_ids, enabled=body.models)
            logger.info("[voting] 完成，共 %d 支股票", len(_vote_results))
        except Exception as e:
            logger.error("[voting] 失敗: %s", e)
        finally:
            with _vote_lock:
                _vote_running = False

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "count": len(body.stock_ids)}

@app.get("/voting/status")
def get_vote_status():
    with _vote_lock:
        running = _vote_running
    return {"status": "running" if running else "idle", "last_count": len(_vote_results)}

@app.get("/voting/results")
def get_vote_results():
    return _vote_results


# ── 開盤跳空預測（盤前參考資訊）──────────────────────────────────────────
@app.get("/gap/predict")
def get_gap_prediction(stock_ids: str = None):
    """
    預測次一交易日的開盤跳空。

    這是**參考資訊而非買賣訊號**——跳空發生在開盤瞬間，事後無法交易。
    之所以做得到，是因為美股隔夜與台股開盤跳空相關高達 +0.66
    （Iteration 15 實測），資訊在開盤即被吸收；也正因如此，
    它對「收盤到收盤」的漲跌預測毫無幫助。

    stock_ids：以逗號分隔，省略則回傳全部可預測的股票。
    """
    import gap_model
    ids = [s.strip() for s in stock_ids.split(',')] if stock_ids else None
    return gap_model.predict_gaps(ids)


# ── 美股（Iteration 32）──────────────────────────────────────────────────────
@app.get("/us/overview")
def get_us_overview(days: int = 60):
    """
    美股總覽：全部標的（Iteration 34 起 23 檔）的最新報價、期間漲跌，加上下一場的開盤跳空預測。

    模型的訊號來源是**台股與韓日的當日盤**（美股開盤前 8 小時已收盤），
    只用美股自身歷史時走查相關僅 0.0085 ≈ 0。所以這一頁真正在回答的是
    「今天亞洲盤這樣走，今晚美股大概開在哪」。
    """
    import us_model
    snap = us_model.market_snapshot(days)
    pred = us_model.predict_gaps()
    by_ticker = {p['ticker']: p for p in pred.get('predictions', [])}
    if snap.get('available'):
        for item in snap['items']:
            item['gap_prediction'] = by_ticker.get(item['ticker'])
    return {'snapshot': snap, 'prediction': pred,
            'freshness': _us_freshness()}


@app.get("/us/gap")
def get_us_gap(tickers: str = None):
    """下一場美股開盤跳空預測。tickers 以逗號分隔，省略則全部。"""
    import us_model
    ids = [s.strip() for s in tickers.split(',')] if tickers else None
    return us_model.predict_gaps(ids)


@app.get("/us/tickers")
def get_us_tickers():
    """美股標的清單（代號、名稱、分類；Iteration 34 起 23 檔）。趨勢預測頁切到美股時的下拉選單用。"""
    from db.connection import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT t.ticker, t.name, t.category, MAX(p.trade_date) AS last_date,
                       COUNT(p.trade_date) AS rows
                  FROM us_tickers t
                  LEFT JOIN us_daily_prices p ON p.ticker = t.ticker
                 GROUP BY t.ticker, t.name, t.category
                 ORDER BY t.category, t.ticker
            """)
            rows = cur.fetchall()
    return {'items': [{'ticker': tk, 'name': name, 'category': cat,
                       'last_date': str(d) if d else None, 'rows': int(n)}
                      for tk, name, cat, d, n in rows]}


def _us_freshness() -> dict:
    """美股頁要看得到資料到哪一天——落後時模型照樣會輸出，不講就看不出來。"""
    import data_freshness
    try:
        return data_freshness.check_exogenous()
    except Exception as e:
        return {'available': False, 'reason': str(e)[:160]}


# ── 週振幅預測（波段選股）─────────────────────────────────────────────────
@app.get("/range/weekly")
def get_weekly_range(stock_ids: str = None, only_significant: bool = False):
    """
    預測未來 5 個交易日的振幅（最高−最低），並標記「顯著偏大」的股票。

    顯著判定同時看兩個維度，避免單一標準誤導：
      相對自身：預測振幅 ≥ 該股歷史中位數的 1.15 倍（排除長期高波動股）
      相對同儕：當日排名前 30%（排除全市場都在震盪的日子）

    **振幅大不代表會漲**——方向仍不可預測，此端點只回答「會不會震」。
    """
    import range_model
    ids = [s.strip() for s in stock_ids.split(',')] if stock_ids else None
    res = range_model.predict_ranges(ids)
    if only_significant and res.get('available'):
        res = {**res, 'results': [r for r in res['results'] if r['is_significant']]}
    return res


# ── 角色化決策 + 本週交易計畫（Iteration 22）───────────────────────────────
# ── 模型目錄（Iteration 31）─────────────────────────────────────────────────
@app.get("/catalog")
def get_catalog(page: str = None, selectable_only: bool = False):
    """
    所有模型的單一事實來源：預測什麼、用哪些資料、可出現在哪些頁面、可信度。

    Iteration 31 之前這件事散落在四個地方各說各話，結果是「預測比對」頁密集
    監控 10 個已證實沒有 edge 的 LSTM，而真正在做買賣決策的四個模型不在那一頁上。
    """
    import model_catalog as cat
    models = cat.all_models(page=page, selectable_only=selectable_only)
    return {
        'models': models,
        'defaults': cat.defaults(page) if page else [],
        'blocks': _describe_blocks(),
        'kind_labels': cat.MODEL_KIND_LABEL,
        'credibility_labels': cat.CREDIBILITY_LABEL,
    }


def _describe_blocks():
    """
    資料區塊清單。取不到就回空——目錄本身不該因為面板模組壞掉而不能看。

    `panel` 住在 UnifiedModel/ 底下，不在 Crawler 的 sys.path 上，所以要自己加。
    """
    try:
        import os
        import sys
        um = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'UnifiedModel')
        if um not in sys.path:
            sys.path.insert(0, um)
        import panel as P
        return P.describe()
    except Exception as e:
        logger.warning('[catalog] 區塊清單不可用：%s', e)
        return []


@app.get("/voting/roles")
def get_role_decision(stock_id: str = Query(...), models: str = None):
    """
    八個角色各自的判斷。方向角色投票、閘門角色否決、紀律角色覆蓋。

    `models` 是逗號分隔的目錄鍵（見 `GET /catalog?page=voting`），
    未指定時用預設集合。被停用的角色**照樣回傳**並標記 `enabled: false`，
    否則使用者看不出自己關掉了什麼。

    回應中的 `credibility` 標註每個角色所依據的模型有沒有走查證據——
    這不是裝飾：使用者有權知道哪些意見有實測支撐、哪些只是還沒被否證。
    """
    import model_catalog as cat
    import roles as role_engine
    import model2_news as m2
    import model3_chip as m3
    import risk_model
    import voting_engine

    selected = cat.resolve([m for m in (models or '').split(',') if m.strip()], 'voting')
    enabled_roles = {cat.CATALOG[k]['role_key'] for k in selected if k in cat.CATALOG}
    lstm_keys = [k for k in selected if k.startswith('lstm:')]

    m1 = voting_engine._get_m1_signal(stock_id, models=lstm_keys or None)
    m2r = m2.get_signal(stock_id)
    m3r = m3.get_signal(stock_id)
    try:
        risk = risk_model.get_risk(stock_id)
    except Exception as e:
        risk = {'reason': f'風險模組不可用：{str(e)[:60]}'}
    rng = voting_engine._get_range_info(stock_id)
    gap_info = voting_engine._get_gap_info(stock_id)
    liq = _get_liquidity_info(stock_id)
    holdings = role_engine.load_holdings()

    out = role_engine.decide(stock_id, m1, m2r, m3r, risk,
                             rng=rng, holding=holdings.get(stock_id), gap=gap_info,
                             liq=liq, enabled=enabled_roles)
    out['selected_models'] = selected
    out['data_blocks'] = cat.blocks_in_use(selected)
    return out


def _get_liquidity_info(stock_id: str):
    """成交量模型的單檔結果。模型不可用時回 None，角色會據此棄權而不是否決。"""
    try:
        import volume_model
        r = volume_model.get_liquidity([stock_id])
        return (r.get('results') or {}).get(str(stock_id).strip())
    except Exception as e:
        logger.warning('[liquidity] %s 不可用：%s', stock_id, e)
        return None


@app.get("/voting/weekly-plan")
def get_weekly_plan(stock_id: str = Query(...)):
    """
    本週 5 個交易日的每日動作（買／賣／續抱／空手）。

    **注意 `deployed` 旗標。** 目前的走查結果是未通過——
    這套每日進出規則在歷史上不如「週一買、週五賣」，
    回應中的 `status_note` 會直接寫明，前端也會照樣顯示。
    """
    import weekly_plan
    return weekly_plan.build_plan(stock_id)


# ── 資料新鮮度（Iteration 27）───────────────────────────────────────────────
@app.on_event("startup")
def _startup_freshness_check():
    """
    服務啟動時檢查「預測比對」與持股用到的股票行情是否為最新，落後就自動補齊。

    在背景執行緒跑：補資料要打外部 API，讓它擋住服務啟動是不對的，
    使用者會以為服務掛了。
    """
    import data_freshness
    data_freshness.run_startup_check(auto_fill=True)


@app.get("/data/freshness")
def get_data_freshness(stock_ids: str = None):
    """
    每檔的最後交易日與落後幾個交易日。

    落後的判準是「市場上有交易日、這檔沒有」，不用日曆天——
    否則連假期間會把所有股票都算成落後。
    """
    import data_freshness
    ids = [s.strip() for s in stock_ids.split(',')] if stock_ids else None
    out = data_freshness.check(ids)
    out['startup'] = data_freshness.last_result()
    return out


@app.get("/data/freshness/exogenous")
def get_data_freshness_exogenous():
    """美股／台指期／韓日指數三張表的最新日期。美股趨勢預測與預測比對頁用。"""
    import data_freshness
    return data_freshness.check_exogenous()


@app.post("/data/backfill/exogenous")
def post_data_backfill_exogenous(days: int = 30):
    """
    把美股／台指期／韓日指數補到最新（與排程 job_exogenous 同一條路徑）。

    美股 23 檔 + 期貨 2 次 ＝ 25 次 FinMind 呼叫，匿名額度 30 次/小時；
    與台股的 /data/backfill 共用同一個額度，連按會用完，回應裡會照實列出失敗的檔。
    """
    import data_freshness
    res = data_freshness.refill_exogenous(days=days)
    status = data_freshness.check_exogenous()
    us = res.get('us') or {}
    failed = us.get('failed') or []
    return {
        'ok': not us.get('error'),
        'result': res,
        'freshness': status,
        'reason': (f"美股 {us.get('rows', '?')} 筆"
                   + (f"（{len(failed)} 檔失敗）" if failed else '')
                   + f"；期貨 {res.get('futures')}；韓日 {res.get('index')}"
                   + ('；補齊後仍落後：' + '、'.join(status.get('problems', []))
                      if status.get('problems') else '')),
    }


@app.post("/data/backfill")
def post_data_backfill(stock_ids: str = None, max_stocks: int = 8):
    """把落後的股票補到最新（受 FinMind 匿名額度限制，一次最多 max_stocks 檔）。"""
    import data_freshness
    ids = [s.strip() for s in stock_ids.split(',')] if stock_ids else None
    return data_freshness.backfill(ids, max_stocks=max_stocks)


# ── 閒置資金一週配置（Iteration 26）─────────────────────────────────────────
@app.get("/cash/plan")
def get_cash_plan(amount: float = Query(..., gt=0),
                  risk_budget: float = Query(0.02, gt=0, le=0.5),
                  max_positions: int = Query(5, ge=1, le=10),
                  exclude_held: bool = False,
                  models: str = None,
                  user_id: int = 1):
    """
    把閒置資金配置到一週的部位上。

    **這裡最大化的是風險調整後的期望價差空間，不是預測報酬。**
    方向不可預測在本專案已被反覆實測（Iteration 11、12），
    Iteration 22 的每日進出策略走查也輸給買進持有，故不做獲利宣稱。
    回應中的 `honesty` 與 `diagnostics` 會直接說明這些限制與配置結果的成因。
    """
    import cash_allocator
    import model_catalog as cat
    selected = cat.resolve([m for m in (models or '').split(',') if m.strip()], 'idlecash')
    out = cash_allocator.allocate(amount, risk_budget, max_positions,
                                  exclude_held=exclude_held, enabled=selected, user_id=user_id)
    out['selected_models'] = selected
    out['data_blocks'] = cat.blocks_in_use(selected)
    return out


# ── 模型版本管理（Iteration 21）─────────────────────────────────────────────
# 「凍結」＝把目前的 candidate 固定成長期服役版本，之後重訓不再動到它，
# 同時自動開出下一版 candidate 繼續迭代。
class FreezeRequest(BaseModel):
    reason: Optional[str] = "manual"
    note: Optional[str] = None


# ── 每週自動預測（Iteration 37）──────────────────────────────────────────────
# GET  /forecast/weekly         最新一次執行（每檔一列：LSTM 兩週摘要 + 各閘門／方向模型）
# GET  /forecast/weekly/status  是否正在執行、下次排程時間
# POST /forecast/weekly/run     手動補跑（背景執行；平常不需要，排程每週日 08:00 自動跑）
@app.get("/forecast/weekly")
def get_weekly_forecast():
    import weekly_forecast
    try:
        return weekly_forecast.latest()
    except Exception as e:
        logger.warning("[weekly] 讀取失敗：%s", e)
        raise HTTPException(500, f"讀取每週預測失敗：{str(e)[:120]}")


@app.get("/forecast/weekly/status")
def get_weekly_forecast_status():
    import weekly_forecast
    return weekly_forecast.status()


@app.post("/forecast/weekly/run")
def trigger_weekly_forecast():
    import weekly_forecast
    if weekly_forecast.status().get("running"):
        return {"status": "already_running"}

    def _run():
        try:
            weekly_forecast.run(trigger="manual")
        except Exception as e:
            logger.error("[weekly] 手動執行失敗：%s", e)

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started"}


@app.get("/models")
def list_models(model_type: str = None):
    """
    所有模型版本 + **線上實測**指標。

    注意這裡的指標與訓練報表的走查指標是兩回事：走查是回頭在歷史上模擬，
    這裡是模型當時真的送出、事後才被實際價格驗證的預測。
    兩者不一致時以這裡為準——它才是模型上線後的真實表現。
    """
    import model_lifecycle
    import model_registry as registry
    try:
        results = model_lifecycle.evaluate_all(model_type)
    except Exception as e:
        raise HTTPException(500, f"評估失敗：{e}")

    # is_serving 是資料庫欄位，但推論端在「沒有任何一版 is_serving」時
    # 會直接拿 candidate 上場（見 loadable_versions 的說明）。只回傳欄位值
    # 會讓前端顯示成「無版本服役」，而實際上有一版正在對外輸出。
    # 這裡補一個 effective_serving，標的是「現在真的在跑的那一版」。
    live = {}
    for v in results:
        mt = v['model_type']
        if mt not in live:
            loaded = registry.loadable_versions(mt) or []
            head = next((ver for ver, _p, serving in loaded if serving), None)
            live[mt] = head['version'] if head else None
        meta = registry.describe(mt) or {}
        v['label'] = meta.get('label', mt)
        v['effective_serving'] = (v['version'] == live[mt])
    return {
        "versions": results,
        "gate": {
            "min_samples": model_lifecycle.MIN_SAMPLES,
            "min_margin": model_lifecycle.MIN_MARGIN,
            "max_p_value": model_lifecycle.MAX_P_VALUE,
            "min_rank_corr": model_lifecycle.MIN_RANK_CORR,
            "min_rank_margin": model_lifecycle.MIN_RANK_MARGIN,
            "note": ("方向類模型須在多數類別基準之上取得 "
                     f"{model_lifecycle.MIN_MARGIN:.0%} 以上的差距，"
                     f"且單尾二項檢定 p ≤ {model_lifecycle.MAX_P_VALUE}；"
                     "純量級模型（振幅／波動率）沒有方向可言，改以排序相關把關。"),
        },
    }


@app.post("/models/{model_type:path}/freeze")
def freeze_model(model_type: str, body: FreezeRequest = FreezeRequest()):
    """手動把目前的 candidate 凍結為長期服役版本，並自動開出下一版 candidate。"""
    import model_registry as registry
    res = registry.freeze(model_type, reason=body.reason or 'manual',
                          note=body.note)
    if not res.get('ok'):
        raise HTTPException(400, res.get('reason', '凍結失敗'))
    return res


@app.post("/models/version/{version_id}/serve")
def serve_version(version_id: int):
    """把服役版本切到指定的凍結版本（candidate 會被重訓覆寫，不可指定）。"""
    import model_registry as registry
    res = registry.set_serving(version_id)
    if not res.get('ok'):
        raise HTTPException(400, res.get('reason', '切換失敗'))
    return res


@app.post("/models/version/{version_id}/retire")
def retire_version(version_id: int):
    """把凍結版本退役（檔案保留，紀錄保留）。"""
    import model_registry as registry
    res = registry.retire(version_id)
    if not res.get('ok'):
        raise HTTPException(400, res.get('reason', '退役失敗'))
    return res


@app.get("/models/ledger-audit")
def get_ledger_audit():
    """
    台帳稽核：該寫的模型今天寫了嗎、到期的預測結算了嗎。

    `/models` 只看得到「有紀錄的版本表現如何」，看不到「某版整批沒寫進來」——
    寫入失敗是靜默的（各 `_log_all` 的例外只記 warning），漏寫的版本在
    `/models` 上只會顯示指標較舊，跟「還沒到期」長得一樣。
    """
    import ledger_audit
    try:
        return ledger_audit.audit()
    except Exception as e:
        logger.warning("[ledger-audit] 失敗：%s", e)
        return {"available": False, "reason": str(e)[:200]}


@app.post("/models/evaluate")
def evaluate_models(report_only: bool = True):
    """
    回填已到期預測 → 重算線上指標 →（report_only=False 時）對達標者自動凍結。

    預設 report_only=True：自動凍結是不可逆的部署決定，
    要它發生必須明確指定，不能因為誰按了「重新整理」就悄悄換掉線上模型。
    """
    import model_lifecycle
    import resolve_predictions
    resolved = resolve_predictions.resolve()
    res = model_lifecycle.run(report_only=report_only)
    return {"resolved": resolved,
            "evaluated": res['evaluated'],
            "frozen": res['frozen'],
            "report_only": report_only}


# ── 模型預測（Stub）───────────────────────────────────────────────────────
# GET /model/predict?stock_id=&model=lstm&days=7
@app.get("/model/predict")
def get_prediction(
    stock_id: str = Query(...),
    model: str = Query("lstm"),
    days: int = Query(7, ge=1, le=30),
):
    # TODO: 待預測模型實作
    return []


# ── 手動重訓（Stub）───────────────────────────────────────────────────────
# POST /model/retrain  Body: { stock_id }
@app.post("/model/retrain")
def retrain_model(body: dict):
    # TODO: 待預測模型實作
    return {"status": "not_implemented", "task_id": None}
