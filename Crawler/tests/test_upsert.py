"""寫入與冪等（測試庫）：同鍵重跑不重複、新聞兩層去重、adj_close 重建、股票主檔同步與殘留列、別名表、日曆與對齊。"""
from datetime import date, datetime

import pytest

from db import repository
from models.stock import StockChipAnalysis, StockDailyPrice, StockForeignHolding

pytestmark = pytest.mark.db


def test_upsert_daily_prices_is_idempotent_and_updates(clean_db):
    db = clean_db
    rows = [StockDailyPrice('2330', date(2026, 9, 22), close_price=2460, volume=100),
            StockDailyPrice('2330', date(2026, 9, 23), close_price=2470, volume=200)]
    assert repository.upsert_daily_prices(rows) == 2
    assert repository.upsert_daily_prices(rows) == 2                              # 重跑：回報處理筆數，表裡仍是 2 列
    assert db.query('SELECT count(*) FROM stock_daily_prices')[0][0] == 2
    rows[0].close_price = 2500
    repository.upsert_daily_prices(rows)
    assert float(db.query("SELECT close_price FROM stock_daily_prices WHERE trade_date='2026-09-22'")[0][0]) == 2500
    assert repository.upsert_daily_prices([]) == 0


def test_upsert_chips_and_foreign_holding_idempotent(clean_db):
    db = clean_db
    chips = [StockChipAnalysis('2330', date(2026, 9, 22), foreign_investor_buy=12480000, investment_trust_buy=860000,
                               dealer_buy=-310000, total_net_buy=13030000)]
    repository.upsert_chip_analysis(chips); repository.upsert_chip_analysis(chips)
    assert db.query('SELECT count(*), max(total_net_buy) FROM stock_chip_analysis')[0] == (1, 13030000)
    hold = [StockForeignHolding('2330', date(2026, 9, 19), foreign_shares=1, foreign_ratio=69.19, foreign_upper_limit_ratio=100, shares_issued=10)]
    repository.upsert_foreign_holding(hold); repository.upsert_foreign_holding(hold)
    assert db.query('SELECT count(*) FROM stock_foreign_holding')[0][0] == 1
    # 持股日期（9/19）可以早於行情日期（9/22），兩張表各記各的
    assert db.query('SELECT max(trade_date) FROM stock_foreign_holding')[0][0] < db.query('SELECT max(trade_date) FROM stock_chip_analysis')[0][0]


def test_raw_news_dedup_by_source_url(clean_db):
    db = clean_db
    arts = [{'platform': 'p', 'title': 'a', 'content': '', 'source_url': 'https://x/1', 'published_at': datetime(2026, 9, 26, 10), 'is_financial': True},
            {'platform': 'p', 'title': 'b', 'content': '', 'source_url': 'https://x/2', 'is_financial': False},
            {'platform': 'p', 'title': '', 'content': '', 'source_url': '', 'is_financial': True}]        # 空 URL → NULL，不撞唯一鍵
    assert repository.insert_raw_news_batch(arts) == (3, 0)
    assert repository.insert_raw_news_batch(arts[:2]) == (0, 2)
    assert db.query("SELECT title, published_at FROM news_crawl_raw WHERE source_url='https://x/1'")[0] == ('a', '2026-09-26T10:00:00')
    assert db.query("SELECT title FROM news_crawl_raw WHERE source_url IS NULL")[0][0] == '(無標題)'


def test_user_news_dedup_by_title_and_day(clean_db):
    """MOPS 同一主旨每月再發：不同日期要各算一則；同日同標題只留一則；沒發布時間只看標題。"""
    db = clean_db
    subject = '台積電（2330）本公司代子公司公告取得固定收益證券'
    arts = [{'platform': 'MOPS重大訊息', 'title': subject, 'content': '', 'tickers': ['2330'], 'published_at': datetime(2026, 8, 23, 9, 5)},
            {'platform': 'MOPS重大訊息', 'title': subject, 'content': '', 'tickers': ['2330'], 'published_at': datetime(2026, 9, 23, 9, 5)},
            {'platform': 'MOPS重大訊息', 'title': subject, 'content': '', 'tickers': ['2330'], 'published_at': datetime(2026, 9, 23, 17, 0)},
            {'platform': '鉅亨網', 'title': '沒時間的新聞', 'content': ''}]
    assert repository.insert_news_articles(arts) == 3
    assert repository.insert_news_articles(arts) == 0
    assert db.query('SELECT count(*) FROM user_news')[0][0] == 3
    assert db.query("SELECT submitted_at FROM user_news WHERE title=%s ORDER BY 1", (subject,))[0][0] == datetime(2026, 8, 23, 9, 5)


def test_rebuild_adj_close_back_adjusts_before_events(clean_db):
    import rebuild_adj_close
    db = clean_db
    db.seed_stock('2409')
    db.seed_prices('2409', [date(2022, 10, 7), date(2022, 10, 11), date(2022, 10, 12)], close=14.70, step=0)
    # 減資：14.70 → 15.87（factor 1.0796）；另塞一筆 factor 異常的除權息要被略過
    db.execute("INSERT INTO stock_capital_reduction (stock_id, ex_date, before_price, reference_price, reason) VALUES ('2409','2022-10-11',14.70,15.87,'彌補虧損')")
    db.execute("INSERT INTO stock_dividend_result (stock_id, ex_date, before_price, reference_price, dividend, dividend_type) VALUES ('2409','2022-10-12',1,999,0,'息')")
    assert rebuild_adj_close.rebuild(['2409']) == 3
    rows = dict((d, float(a)) for d, a in db.query("SELECT trade_date, adj_close FROM stock_daily_prices WHERE stock_id='2409' ORDER BY 1"))
    factor = 15.87 / 14.70
    assert rows[date(2022, 10, 7)] == round(14.70 * factor, 4)      # 事件前按比例放大
    assert rows[date(2022, 10, 11)] == 14.70                         # 事件日起等於原始收盤
    assert rows[date(2022, 10, 12)] == 14.70
    assert rebuild_adj_close.rebuild(['2409']) == 3                  # 重跑結果不變
    assert dict((d, float(a)) for d, a in db.query("SELECT trade_date, adj_close FROM stock_daily_prices WHERE stock_id='2409'")) == rows


def test_sync_stock_info_upsert_and_orphans(clean_db):
    import sync_stock_info
    db = clean_db
    db.seed_prices('2330', [date(2026, 9, 22)])
    db.seed_prices('2303', [date(2026, 9, 22)])
    repository.upsert_stock_info('2330', '台積電', 'twse', '半導體業')
    repository.upsert_stock_info('2330', '台積電', 'twse', '電子工業')          # 重跑更新產業別
    repository.upsert_stock_info('9999', '9999')                             # 名稱=代碼且沒行情 → 殘留列（下市）
    repository.upsert_stock_info('8888', '')                                 # 空名稱、沒行情 → 殘留列
    assert sync_stock_info.price_stock_ids() == ['2303', '2330']
    assert sorted(sync_stock_info.orphan_info_rows()) == ['8888', '9999']
    assert db.query("SELECT industry_type FROM stock_info WHERE stock_id='2330'")[0][0] == '電子工業'
    assert db.query('SELECT count(*) FROM stock_info')[0][0] == 3            # 2330 只有一列（upsert）


def test_alias_seed_and_match(clean_db):
    import news_alias
    db = clean_db
    repository.upsert_stock_info('2330', '台積電'); repository.upsert_stock_info('2327', '國巨*'); repository.upsert_stock_info('2883', '凱基金')
    repository.upsert_stock_info('1234', '台灣')                              # 太泛的名稱不當別名
    n = news_alias.seed()
    assert n > 0 and news_alias.seed() == 0                                   # 重跑不重複
    assert db.query("SELECT count(*) FROM instrument_alias WHERE alias='台灣'")[0][0] == 0
    m = news_alias.load_alias_map(force=True)
    assert sorted(news_alias.match('國巨 與 TSMC、開發金', m)) == ['2327', '2330', '2883']


def test_calendar_and_link_news(clean_db):
    import news_align
    db = clean_db
    db.seed_prices('2330', [date(2026, 9, 22), date(2026, 9, 23), date(2026, 9, 24)])
    assert news_align.build_calendar() == 3 and news_align.build_calendar() == 0
    assert news_align.load_open_days('TW') == [date(2026, 9, 22), date(2026, 9, 23), date(2026, 9, 24)]
    db.execute("INSERT INTO user_news (platform, title, content, tickers, submitted_at) VALUES ('p','a','', ARRAY['2330','2330'], '2026-09-22 15:00'), ('p','b','', ARRAY['2303'], '2026-09-23 09:00'), ('p','c','', NULL, '2026-09-23 09:00')")
    assert news_align.link_news() == 2                                        # 重複 ticker 合併、沒 ticker 的不連
    links = db.query('SELECT ticker, effective_date, lag_days FROM news_price_link ORDER BY ticker')
    assert links == [('2303', date(2026, 9, 23), 0), ('2330', date(2026, 9, 23), 1)]
    assert news_align.link_news() == 2 and db.query('SELECT count(*) FROM news_price_link')[0][0] == 2     # upsert
