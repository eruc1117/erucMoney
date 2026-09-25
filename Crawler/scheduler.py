"""
排程器（依 AI/UserDoc/request.md 第六節「資料更新頻率」）

使用 APScheduler 定期執行三項任務（時區 Asia/Taipei）：
  - 每日 18:00  股價 + 籌碼 + 外資持股更新（FinMind，追蹤中股票）
                → stock_daily_prices / stock_chip_analysis / stock_foreign_holding
  - 每小時 :05  新聞爬蟲 + 情緒特徵計算 → user_news / news_features
  - 每日 20:00  三模型加權投票 → voting_results

啟動：python main.py --mode schedule
      或以 Windows 工作排程器常駐（Iteration 36）：install_scheduler_task.ps1

## 為什麼要常駐（Iteration 36）

排程器原本只在 start-dev.bat 被人打開時才存在；沒開就整天沒跑，
症狀是「今天沒資料」，看起來像 FinMind 掛了，其實是程序根本不在。
現在：
  · 日誌寫到 logs/scheduler.log（無主控台時也看得到發生了什麼）
  · 啟動時補跑當天已錯過的每日任務（`_catch_up`），一天最多一次
  · 啟動時用鉅亨網 API 補回離線期間漏掉的新聞（`_catch_up_news`，Iteration 38）
  · install_scheduler_task.ps1 把它註冊成登入即啟動、失敗自動重啟的工作
"""

import logging
import os
import sys
from datetime import date, datetime, timedelta
from logging.handlers import RotatingFileHandler

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config import SCHEDULE

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
RUN_WEEKLY = (8, 0)     # 每週日 08:00（與 weekly_forecast.RUN_HOUR 一致）


def _setup_logging():
    """檔案日誌一定有；主控台日誌只在有主控台時加（pythonw 沒有 stderr）。"""
    os.makedirs(LOG_DIR, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fh = RotatingFileHandler(os.path.join(LOG_DIR, "scheduler.log"),
                             maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if sys.stderr is not None:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)


_setup_logging()
logger = logging.getLogger(__name__)


def _tracked_stock_ids() -> list[str]:
    """自 stock_info 取得追蹤中的股票清單（取代舊版寫死清單）。"""
    from db.connection import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stock_id FROM stock_info WHERE is_tracking = TRUE ORDER BY stock_id")
            return [r[0] for r in cur.fetchall()]


def _refresh_adj_close(ids: list[str]) -> None:
    """更新公司行動（除權息／減資）後重建 adj_close。

    為何要綁在股價更新之後跑：寫入行情的路徑（本 job 與 backfill_prices）
    都只寫 close_price，**adj_close 一律留 NULL**。而 Iteration 18 起
    「算報酬一律用 adj_close」，所以少了這一步，每天新增的那一列對所有
    報酬計算等於不存在——而且症狀是「今天還沒資料」，不像壞掉，沒人會查。

    事件抓取失敗不阻擋重建：用過期事件表重建，只有跨越今天這條邊界的報酬會錯；
    完全不重建則是最新一天整個沒有值，後者嚴重得多。
    """
    import backfill_dividend
    import rebuild_adj_close

    # 180 天窗口：全歷史事件早已在事件表裡，每日只需補上新宣告的那幾筆。
    start = date.today() - timedelta(days=180)
    for name, fn in (
        ("除權息", lambda: backfill_dividend.fetch_dividends(ids, start)[0]),
        ("減資",   lambda: rebuild_adj_close.fetch_reductions(ids, start)),
    ):
        try:
            logger.info("[排程/adj] %s事件更新 %d 筆", name, fn())
        except Exception as e:
            logger.warning("[排程/adj] %s事件更新失敗，沿用既有事件表：%s", name, e)

    updated = rebuild_adj_close.rebuild(ids)

    # 重建完仍有 NULL 就是真的壞了（例如 close_price <= 0 被 rebuild 略過）。
    # 這條鏈上其他步驟都是靜默的，這裡刻意出聲。
    from db.connection import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM stock_daily_prices
                WHERE trade_date = (SELECT MAX(trade_date) FROM stock_daily_prices)
                  AND adj_close IS NULL
            """)
            missing = cur.fetchone()[0]
    if missing:
        logger.warning("[排程/adj] 重建 %d 筆，但最新交易日仍有 %d 檔的 adj_close 是 NULL",
                       updated, missing)
    else:
        logger.info("[排程/adj] 重建 %d 筆，最新交易日 adj_close 完整", updated)


def job_stock():
    """每日 18:00：FinMind 抓近 7 天行情 + 籌碼 + 外資持股（涵蓋假日補班），
    upsert 冪等寫入，再更新公司行動並重建 adj_close。

    外資持股（Iteration 35）每檔多一次呼叫：26 檔 × 3 = 78 次。
    持股失敗不擋行情與籌碼——它只供「法人持股」頁顯示，不進任何模型。"""
    from scrapers.finmind_scraper import FinMindScraper
    from db.repository import upsert_daily_prices, upsert_chip_analysis, upsert_foreign_holding

    ids = _tracked_stock_ids()
    if not ids:
        logger.warning("[排程/stock] 無追蹤股票，跳過")
        return

    today = date.today()
    scraper = FinMindScraper(stock_ids=ids, start_date=today - timedelta(days=7), end_date=today)

    prices = scraper.fetch_prices()
    price_count = upsert_daily_prices([p for p in prices if p])
    chips = scraper.fetch_chips()
    chip_count = upsert_chip_analysis(chips)
    try:
        hold_count = upsert_foreign_holding(scraper.fetch_foreign_holding())
    except Exception as e:
        hold_count = 0
        logger.warning("[排程/stock] 外資持股更新失敗（不影響行情與籌碼）：%s", e)

    logger.info("[排程/stock] 完成：%d 檔，行情 %d 筆，籌碼 %d 筆，外資持股 %d 筆",
                len(ids), price_count, chip_count, hold_count)

    _refresh_adj_close(ids)


def job_news():
    """每小時：爬取公開 RSS／鉅亨網 API 新聞（含 22 檔個股定向），寫入 user_news，
    並對每檔追蹤股票計算情緒特徵落地 news_features（model2 內建 upsert）。

    Iteration 10 起改用 rss_news_scraper：舊的首頁標題爬法產出的內文恆為空、
    個股標記恆為空。實測單次約 4 分鐘，適合每小時排程。"""
    from scrapers.news_scraper import NewsScraper
    from db.repository import insert_raw_news_batch, insert_news_articles
    import model2_news

    articles = NewsScraper().scrape_all()
    insert_raw_news_batch(articles)
    fin_articles = [a for a in articles if a.get('is_financial', True)]
    count = insert_news_articles(fin_articles)
    logger.info("[排程/news] 原始 %d 則 → 財金 %d 則寫入 user_news", len(articles), count)

    for sid in _tracked_stock_ids():
        model2_news.get_signal(sid)   # 內部會 upsert news_features
    logger.info("[排程/news] 情緒特徵計算完成")
    _refresh_news_history()


def _refresh_news_history():
    """
    Iteration 38：去重 → 日級對齊 → 歷史特徵（近 7 天增量）。
    news_schema.py 尚未套用（表或欄位不存在）時記一行略過，不影響原本的抓取與 M2。
    """
    try:
        import news_align
        import news_dedup
        since = date.today() - timedelta(days=7)
        d = news_dedup.run(since)
        n_link = news_align.link_news(since)
        n_feat = news_align.compute_daily_features(since)
        logger.info("[排程/news] 去重 %d 群／%d 重複；對齊 %d 筆；歷史特徵 %d 列",
                    d["groups"], d["duplicates"], n_link, n_feat)
    except Exception as e:
        logger.info("[排程/news] 對齊／歷史特徵略過（%s）", e)


def job_vote():
    """每日 20:00：對全部追蹤股票執行三模型加權投票，寫入 voting_results。"""
    from voting_engine import run_vote_batch

    ids = _tracked_stock_ids()
    if not ids:
        logger.warning("[排程/vote] 無追蹤股票，跳過")
        return
    results = run_vote_batch(ids)
    logger.info("[排程/vote] 完成 %d 檔投票", len(results))


def job_freshness():
    """
    每日 17:30：檢查「預測比對」與持股用到的股票行情是否落後，落後就補齊。

    啟動檢查只涵蓋「重啟那一刻」；服務長時間不重啟時，資料一樣會落後，
    而比對頁只會顯示「尚未到期」，看不出是沒抓到。
    排在 18:00 的股價更新之前，讓它先把缺口補起來。
    """
    import data_freshness

    status = data_freshness.check()
    if not status.get('available'):
        logger.warning("[排程/freshness] 檢查失敗：%s", status.get('reason'))
        return
    stale = status.get('stale', [])
    if not stale:
        logger.info("[排程/freshness] %d 檔皆為最新（市場基準日 %s）",
                    len(status['items']), status['market_last'])
        return
    res = data_freshness.backfill()
    logger.info("[排程/freshness] %s", res.get('reason'))


def job_exogenous():
    """
    每日 06:00 與 19:00：更新美股、台指期、韓日指數。

    這三張表在 Iteration 32 之前**完全沒有排程**，只能手動跑 backfill_*.py。
    後果不是「畫面顯示沒資料」而是更難發現的那種：跳空模型照樣輸出預測，
    只是餵進去的美股隔夜是三天前的——線上看起來一切正常。

    為什麼是這兩個時點（台北時間）：

        06:00  美股前一場 04:00 收盤、台指期夜盤 05:00 收盤 → 兩者都已完整
        19:00  台指期日盤 13:45、韓日 14:30 收盤 → 供 20:00 的美股跳空預測使用

    美股 23 檔 + 期貨 2 次 ＝ 25 次 FinMind 呼叫，在匿名額度 30 次/小時內；
    與 18:00 的股價更新錯開，避免兩者相加超過額度。
    """
    import data_freshness

    res = data_freshness.refill_exogenous(days=30)
    us = res.get('us', {})
    logger.info("[排程/外生] 美股 %s 筆%s；期貨 %s；韓日 %s 筆",
                us.get('rows', '?'),
                f"（{len(us['failed'])} 檔失敗）" if us.get('failed') else '',
                res.get('futures'), res.get('index'))

    status = data_freshness.check_exogenous()
    for p in status.get('problems', []):
        logger.warning("[排程/外生] 補齊後仍落後：%s", p)


def job_us_predict():
    """
    每日 20:00：寫入美股開盤跳空預測（美股 21:30 開盤前）。

    時點是這個模型的全部意義所在——它的特徵是台股與韓日的**當日**盤，
    在美股開盤前 8 小時就收完了。跑在開盤之後，台帳記的就不是預測而是回顧。
    """
    import us_model

    res = us_model.predict_gaps()
    if not res.get('available'):
        logger.warning("[排程/美股] 預測不可用：%s", res.get('reason'))
        return
    ups = sum(1 for p in res['predictions'] if p['gap_pct'] > 0)
    logger.info("[排程/美股] 基準 %s → 預測 %s 那一場：%d 檔開高、%d 檔開低"
                "（台股資訊取自 %s）",
                res['base_date'], res['target_session'],
                ups, len(res['predictions']) - ups, res.get('tw_session'))


def job_weekly_forecast(trigger: str = "schedule"):
    """
    每週日 08:00：用所有可用模型對所有已有股票預測下一週與下下週，存表直接顯示。

    需要 LSTM 預測服務（:8001）在線；沒在線時十個 LSTM 會被記成錯誤、其餘模型照跑，
    畫面上會看到哪些模型缺席，不會靜靜少一塊。
    """
    import weekly_forecast

    res = weekly_forecast.run(trigger=trigger)
    if res.get("status") == "already_running":
        logger.info("[排程/weekly] 已在執行中，略過")
        return
    logger.info("[排程/weekly] run %s：%d 列、%d 個模型、%d 個錯誤",
                res.get("run_id"), res.get("rows", 0), res.get("models", 0), res.get("errors", 0))


def job_model_review():
    """
    每日 21:00：回填已到期的模型預測，重算各版本的線上實測指標。

    **這裡刻意不執行自動凍結**（report_only=True）。凍結會換掉線上服務的模型，
    是不可逆的部署決定；讓它在無人看管的排程裡自己發生，等於把
    「模型換版」交給一個沒人審視過的門檻。指標每天更新，凍結由使用者
    在前端按下，或由人明確執行 `python model_lifecycle.py`。
    """
    import ledger_audit
    import model_lifecycle
    import resolve_predictions

    r = resolve_predictions.resolve()
    res = model_lifecycle.run(report_only=True)
    ready = [f"{v['model_type']} v{v['version']}"
             for v in res['results'] if v['gate_passed']]
    logger.info("[排程/model] 回填 %d 筆，評估 %d 個版本%s",
                r['resolved'], res['evaluated'],
                ("；達標可凍結：" + "、".join(ready)) if ready else "")

    # 稽核排在回填之後：先結算再查，才不會把「本來就還沒跑結算」報成漏結算。
    # 這是整條鏈上唯一會出聲的地方——寫台帳與結算的失敗都是靜默的。
    try:
        a = ledger_audit.audit()
        for p in a.get('problems', []):
            logger.warning("[排程/台帳稽核] %s", p)
        if a.get('available') and not a.get('problems'):
            logger.info("[排程/台帳稽核] %d 個版本覆蓋正常（基準日 %s）",
                        len(a['coverage']), a['market_last'])
    except Exception as e:
        logger.warning("[排程/台帳稽核] 稽核失敗：%s", e)


def _max_trade_date(table: str, col: str = "trade_date"):
    from db.connection import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT max({col})::text FROM {table}")
            row = cur.fetchone()
    return row[0] if row and row[0] else None


def _catch_up_news():
    """
    啟動時把「程序不在的期間」漏掉的新聞補回來（Iteration 38）。

    新聞排程每小時跑一次，但排程器只在電腦開著時活著；RSS 只給最近幾十則，
    關機三天再開就永遠少三天。鉅亨網分類 API 支援 startAt/endAt，所以用它
    把上次抓取到現在的空洞補上，再照常跑一次即時抓取。
    寫入都是 ON CONFLICT / 標題查重，重複執行無副作用，不受每日標記限制。
    """
    from db.connection import get_conn
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT max(scraped_at) FROM news_crawl_raw")
                last = cur.fetchone()[0]
    except Exception as e:
        logger.warning("[排程/catch-up] 讀取新聞最後抓取時間失敗：%s", e)
        return False
    now = datetime.now()
    if last and now - last < timedelta(hours=2):
        logger.info("[排程/catch-up] 新聞最後抓取 %s，兩小時內，不必補", last)
        return False
    since = (last - timedelta(hours=1)) if last else now - timedelta(days=7)
    logger.info("[排程/catch-up] 新聞空洞 %s ~ %s，用鉅亨網 API 補", since, now)
    import backfill_news
    t = backfill_news.backfill_gap(since, categories=("tw_stock", "us_stock"))
    logger.info("[排程/catch-up] 新聞補回 %d 則（user_news +%d），接著跑即時抓取",
                t["fetched"], t["news_inserted"])
    job_news()
    return True


def _catch_up():
    """
    啟動時補跑「今天該跑、但程序當時不在」的每日任務。

    APScheduler 的 cron 任務在程序不在時不會補跑（沒有持久化 jobstore）；
    這正是 9/19 18:00 沒更新的原因。規則：
      · 只補當天已過時間點的任務，且只在資料確實落後時（避免假日與重複登入白燒額度）
      · 一天最多補一次：logs/catchup_YYYY-MM-DD 當作標記
      · 順序沿用排程：股價 → 投票 → 模型回填評估
    """
    now = datetime.now()
    today = now.date()
    try:
        _catch_up_news()          # 新聞空洞不受每日標記與週末限制
    except Exception as e:
        logger.warning("[排程/catch-up] 新聞補跑失敗：%s", e)
    marker = os.path.join(LOG_DIR, f"catchup_{today.isoformat()}")
    if os.path.exists(marker):
        logger.info("[排程/catch-up] 今日已補跑過，略過")
        return
    if today.weekday() >= 5:
        logger.info("[排程/catch-up] 週末，略過")
        return

    def passed(hh, mm):
        return (now.hour, now.minute) >= (hh, mm)

    ran = []
    try:
        sc = SCHEDULE["stock_cron"]
        if passed(sc["hour"], sc["minute"]):
            last = _max_trade_date("stock_daily_prices")
            if last and last < today.isoformat():
                logger.info("[排程/catch-up] 行情最後日 %s 早於今天，補跑股價更新", last)
                job_stock(); ran.append("stock")
            else:
                logger.info("[排程/catch-up] 行情已是 %s，股價更新不必補", last)

        vc = SCHEDULE["vote_cron"]
        if passed(vc["hour"], vc["minute"]):
            last = _max_trade_date("voting_results", "vote_date")
            if not last or last < today.isoformat():
                logger.info("[排程/catch-up] 投票最後日 %s，補跑投票", last)
                job_vote(); ran.append("vote")

        if passed(21, 0) and ran:
            job_model_review(); ran.append("model_review")

        # 每週預測：上個週日 08:00 以來沒跑過就補（不受每日標記限制，另有自己的判準）
        import weekly_forecast
        if weekly_forecast.due():
            logger.info("[排程/catch-up] 上個週日的每週預測沒跑，補跑")
            job_weekly_forecast(trigger="catch_up"); ran.append("weekly_forecast")
    except Exception as e:
        logger.warning("[排程/catch-up] 補跑中斷：%s", e)
    finally:
        with open(marker, "w") as f:
            f.write(",".join(ran) or "nothing")
    logger.info("[排程/catch-up] 完成：%s", "、".join(ran) if ran else "無需補跑")


def start():
    scheduler = BlockingScheduler(timezone="Asia/Taipei")

    stock_cron = SCHEDULE["stock_cron"]
    scheduler.add_job(
        job_stock,
        trigger=CronTrigger(hour=stock_cron["hour"], minute=stock_cron["minute"], timezone="Asia/Taipei"),
        id="job_stock", name="股價+籌碼更新",
        max_instances=1, misfire_grace_time=600,
    )

    news_cron = SCHEDULE["news_cron"]
    scheduler.add_job(
        job_news,
        trigger=CronTrigger(minute=news_cron["minute"], timezone="Asia/Taipei"),
        id="job_news", name="新聞爬蟲+情緒特徵",
        max_instances=1, misfire_grace_time=600,
    )

    vote_cron = SCHEDULE["vote_cron"]
    scheduler.add_job(
        job_vote,
        trigger=CronTrigger(hour=vote_cron["hour"], minute=vote_cron["minute"], timezone="Asia/Taipei"),
        id="job_vote", name="三模型加權投票",
        max_instances=1, misfire_grace_time=1200,
    )

    # 新鮮度檢查排在股價更新之前，先把缺口補起來
    scheduler.add_job(
        job_freshness,
        trigger=CronTrigger(hour=17, minute=30, timezone="Asia/Taipei"),
        id="job_freshness", name="行情新鮮度檢查+補齊",
        max_instances=1, misfire_grace_time=1800,
    )

    # 外生資料（美股／台指期／韓日）跑兩次：早上收前一場，傍晚收當日亞洲盤
    for hh in (6, 19):
        scheduler.add_job(
            job_exogenous,
            trigger=CronTrigger(hour=hh, minute=10, timezone="Asia/Taipei"),
            id=f"job_exogenous_{hh}", name=f"外生資料更新（{hh:02d}:10）",
            max_instances=1, misfire_grace_time=1800,
        )

    # 美股跳空預測要在美股開盤（夏令 21:30 台北）之前跑完
    scheduler.add_job(
        job_us_predict,
        trigger=CronTrigger(hour=20, minute=0, timezone="Asia/Taipei"),
        id="job_us_predict", name="美股開盤跳空預測",
        max_instances=1, misfire_grace_time=3600,
    )

    # 每週日 08:00：全模型預測下一週與下下週（Iteration 37）
    scheduler.add_job(
        job_weekly_forecast,
        trigger=CronTrigger(day_of_week="sun", hour=RUN_WEEKLY[0], minute=RUN_WEEKLY[1], timezone="Asia/Taipei"),
        id="job_weekly_forecast", name="每週全模型預測",
        max_instances=1, misfire_grace_time=6 * 3600,
    )

    # 模型回填與評估排在投票之後一小時，確保當日的預測都已寫入台帳
    scheduler.add_job(
        job_model_review,
        trigger=CronTrigger(hour=21, minute=0, timezone="Asia/Taipei"),
        id="job_model_review", name="模型預測回填+線上實測評估",
        max_instances=1, misfire_grace_time=1800,
    )

    logger.info("排程器啟動：股價每日 %02d:%02d ／ 新聞每小時 :%02d ／ 投票每日 %02d:%02d"
                " ／ 新鮮度每日 17:30 ／ 外生資料 06:10 與 19:10"
                " ／ 美股跳空預測 20:00 ／ 模型評估每日 21:00 ／ 每週日 08:00 全模型預測（Ctrl+C 停止）",
                stock_cron["hour"], stock_cron["minute"],
                news_cron["minute"],
                vote_cron["hour"], vote_cron["minute"])
    _catch_up()
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("排程器已停止")
