"""全市場股票池與日線（Iteration 48）：交易所檔解析、股票池收錄規則、寫入冪等、還原價、偏差檢查。"""
import json
from datetime import date

import pytest

import market_universe
from scrapers import exchange_daily as ex
from tests.conftest import fixture_text

pytestmark = []


def _fx(name):
    return json.loads(fixture_text(name))


# ── 數值與日期 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize('raw, expected', [
    ('1,234.50', 1234.5), (' 2,460.00 ', 2460.0), ('--', None), ('---', None), ('', None), (None, None),
    ('X', None), ('除息', None), ('+0.25', 0.25), ('-0.18', -0.18), ('１,０００', 1000.0),
])
def test_num(raw, expected):
    assert ex._num(raw) == expected


@pytest.mark.parametrize('raw, expected', [
    ('113/07/01', date(2024, 7, 1)), ('113年07月01日', date(2024, 7, 1)), ('107/3/5', date(2018, 3, 5)), ('', None), ('abc', None),
])
def test_roc_date(raw, expected):
    assert ex.roc_date(raw) == expected


def test_sign_from_html_cell():
    assert ex._sign('<p style= color:red>+</p>') == 1
    assert ex._sign("<p style ='color:green'>-</p>") == -1
    assert ex._sign(' ') == 0 and ex._sign('') == 0
    assert ex._sign('X') is None                      # 除權息日：不可比


# ── 證交所每日檔 ──────────────────────────────────────────────────────────────
def test_parse_twse_daily_rows_and_indexes():
    rows, idx = ex.parse_twse_daily(_fx('twse_mi_index.json'))
    by = {r['stock_id']: r for r in rows}
    assert '2330' in by and '0050' in by and '1101B' in by          # 解析不篩選；篩選在股票池那一層
    r = by['2330']
    assert r['trade_date'] == date(2024, 11, 5) and r['source'] == 'twse'
    assert r['close_price'] > 0 and r['high_price'] >= r['low_price'] and r['volume'] > 0 and r['turnover_value'] > 0
    assert r['transaction_count'] > 0
    assert all(k in r for k in ('open_price', 'change_value'))
    # 漲跌 = 符號 × 價差；0050 當天 +0.70
    assert by['0050']['change_value'] == pytest.approx(0.70)
    # 無成交（'--'）的證券被略過
    assert '00625K' not in by and '00643K' not in by
    # 收盤 0.00 也是沒成交，不能當價格
    zero = {'stat': 'OK', 'date': '20241105', 'tables': [{'title': '每日收盤行情', 'fields': ['證券代號', '證券名稱', '成交股數', '成交筆數', '成交金額', '開盤價', '最高價', '最低價', '收盤價', '漲跌(+/-)', '漲跌價差'],
                                                           'data': [['1341', 'x', '0', '0', '0', '0.00', '0.00', '0.00', '0.00', ' ', '0.00']]}]}
    assert ex.parse_twse_daily(zero) == ([], {})
    assert idx[ex.TAIEX_TR_NAME] > idx[ex.TAIEX_NAME] > 0           # 報酬指數（含息）高於價格指數


def test_parse_twse_daily_holiday_is_empty():
    assert ex.parse_twse_daily(_fx('twse_mi_index_holiday.json')) == ([], {})
    assert ex.parse_twse_daily({}) == ([], {})
    assert ex.parse_twse_daily(None) == ([], {})


# ── 櫃買每日檔 ────────────────────────────────────────────────────────────────
def test_parse_tpex_daily_rows():
    rows = ex.parse_tpex_daily(_fx('tpex_otc_daily.json'))
    by = {r['stock_id']: r for r in rows}
    assert '3373' in by and '00679B' in by
    r = by['3373']
    assert r['trade_date'] == date(2024, 11, 5) and r['source'] == 'tpex'
    assert r['close_price'] > 0 and r['open_price'] > 0 and r['volume'] > 0 and r['turnover_value'] > 0 and r['transaction_count'] > 0
    # 漲跌欄直接是帶號數字
    assert by['00679B']['change_value'] == pytest.approx(0.25)


def test_parse_tpex_daily_holiday_is_empty():
    assert ex.parse_tpex_daily(_fx('tpex_otc_daily_holiday.json')) == []
    assert ex.parse_tpex_daily({'stat': 'ok', 'date': '20240101', 'tables': []}) == []


# ── 除權息與減資 ──────────────────────────────────────────────────────────────
def test_parse_exright_both_markets():
    tw = ex.parse_twse_exright(_fx('twse_twt49u.json'))
    assert tw and tw[0]['stock_id'] == '1101' and tw[0]['ex_date'] == date(2024, 7, 1)
    assert tw[0]['before_price'] == 34.2 and tw[0]['reference_price'] == 33.2 and tw[0]['dividend'] == 1.0 and tw[0]['dividend_type'] == '息'
    assert {'stock_id', 'ex_date', 'before_price', 'reference_price', 'dividend', 'dividend_type'} <= set(tw[0])
    tp = ex.parse_tpex_exright(_fx('tpex_exdailyq.json'))
    assert tp and tp[0]['stock_id'] == '3373' and tp[0]['ex_date'] == date(2024, 7, 1)
    assert tp[0]['before_price'] == 27.0 and tp[0]['reference_price'] == 26.0 and tp[0]['dividend_type'] == '除息'
    assert ex.parse_twse_exright({'stat': '很抱歉'}) == [] and ex.parse_tpex_exright({'stat': 'ok', 'tables': []}) == []


def test_parse_capital_reduction():
    rows = ex.parse_twse_capital_reduction(_fx('twse_twtauu.json'))
    assert rows and rows[0]['stock_id'] == '3432' and rows[0]['ex_date'] == date(2024, 1, 22)
    assert rows[0]['before_price'] == 10.65 and rows[0]['reference_price'] == 19.69 and rows[0]['reason'] == '彌補虧損'
    assert rows[0]['reference_price'] > rows[0]['before_price']      # 減資：參考價高於前收（方向與除息相反）


# ── 股票池收錄規則 ────────────────────────────────────────────────────────────
INFO = [
    {'industry_category': '半導體業', 'stock_id': '2330', 'stock_name': '台積電', 'type': 'twse', 'date': '1994-09-05'},
    {'industry_category': '電子工業', 'stock_id': '2330', 'stock_name': '台積電', 'type': 'twse', 'date': '1994-09-05'},
    {'industry_category': '電子工業', 'stock_id': '3373', 'stock_name': '熱映', 'type': 'tpex', 'date': '2009-01-01'},
    {'industry_category': '光電業', 'stock_id': '3373', 'stock_name': '熱映', 'type': 'tpex', 'date': '2010-05-05'},
    {'industry_category': 'ETF', 'stock_id': '0050', 'stock_name': '元大台灣50', 'type': 'twse', 'date': '2003-06-30'},
    {'industry_category': '水泥工業', 'stock_id': '1101B', 'stock_name': '台泥乙特', 'type': 'twse', 'date': '2020-01-01'},
    {'industry_category': '存託憑證', 'stock_id': '910322', 'stock_name': '康師傅-DR', 'type': 'twse', 'date': '2009-12-16'},
    {'industry_category': '生技醫療業', 'stock_id': '6472', 'stock_name': '保瑞', 'type': 'emerging', 'date': '2015-01-01'},
    {'industry_category': 'Index', 'stock_id': 'TAIEX', 'stock_name': '加權指數', 'type': 'twse', 'date': 'None'},
    {'industry_category': '金融保險業', 'stock_id': '2881', 'stock_name': '富邦金', 'type': 'tpex', 'date': '2001-12-19'},
    {'industry_category': '金融保險業', 'stock_id': '2881', 'stock_name': '富邦金', 'type': 'twse', 'date': '2001-12-19'},
]
DELISTED = [
    {'date': '2018-04-30', 'stock_id': '2311', 'stock_name': '日月光'},
    {'date': '2023-04-21', 'stock_id': '00732', 'stock_name': '國泰RMB短期報酬'},
    {'date': '2024-07-01', 'stock_id': '3373', 'stock_name': '熱映'},
]


def test_build_rows_filters_and_merges():
    rows = {r['stock_id']: r for r in market_universe.build_rows(INFO, DELISTED)}
    assert set(rows) == {'2330', '3373', '2881', '2311'}             # ETF、特別股、TDR、興櫃、指數、00732 都不收
    assert rows['2330']['industry_type'] == '半導體業'                 # 具體產業別勝過泛用「電子工業」
    assert rows['3373']['industry_type'] == '光電業' and rows['3373']['listing_date'] is None   # date 欄不是上市日，不用
    assert rows['3373']['delisted_date'] == date(2024, 7, 1)          # 下市表對上現行清單：標下市日
    assert rows['2881']['market_type'] == 'twse'                      # 轉上市：上市優先
    assert rows['2311'] == {'stock_id': '2311', 'stock_name': '日月光', 'market_type': None, 'industry_type': None,
                            'listing_date': None, 'delisted_date': date(2018, 4, 30)}   # 只在下市表：仍收，欄位留空
    assert rows['2330']['delisted_date'] is None
    assert market_universe.build_rows([], []) == []


# ── 資料庫：寫入、股票池、還原價、檢查 ─────────────────────────────────────────
@pytest.mark.db
def test_upsert_prices_idempotent_and_universe_ids(clean_db):
    import market_data
    db = clean_db
    market_universe.upsert([
        {'stock_id': '2330', 'stock_name': '台積電', 'market_type': 'twse', 'industry_type': '半導體業', 'listing_date': date(1994, 9, 5), 'delisted_date': None},
        {'stock_id': '2311', 'stock_name': '日月光', 'market_type': None, 'industry_type': None, 'listing_date': None, 'delisted_date': date(2018, 4, 30)},
        {'stock_id': '6999', 'stock_name': '新股', 'market_type': 'tpex', 'industry_type': '其他', 'listing_date': date(2025, 1, 2), 'delisted_date': None},
    ])
    assert market_universe.ids() == ['2311', '2330', '6999']
    assert market_universe.ids(include_delisted=False) == ['2330', '6999']
    assert market_universe.ids(on=date(2018, 6, 1)) == ['2330']                        # 2311 已下市、6999 還沒上市
    # 重新同步：下市表不再列 2311 → delisted_date 會被清掉（EXCLUDED 直接覆蓋）；其他欄位空值不覆蓋既有
    market_universe.upsert([{'stock_id': '2330', 'stock_name': None, 'market_type': None, 'industry_type': None, 'listing_date': None, 'delisted_date': None}])
    assert db.query("SELECT stock_name, industry_type FROM market_universe WHERE stock_id='2330'")[0] == ('台積電', '半導體業')

    rows = [{'stock_id': '2330', 'trade_date': date(2024, 11, 4), 'close_price': 1000.0, 'open_price': 990.0, 'high_price': 1005.0,
             'low_price': 985.0, 'volume': 100, 'turnover_value': 1e8, 'transaction_count': 10, 'change_value': 5.0, 'source': 'twse'},
            {'stock_id': '2330', 'trade_date': date(2024, 11, 5), 'close_price': 1010.0, 'source': 'tpex'}]
    assert market_data.upsert_prices(rows) == 2 and market_data.upsert_prices(rows) == 2
    assert db.query('SELECT count(*) FROM market_daily_prices')[0][0] == 2
    rows[1]['close_price'] = 1020.0
    market_data.upsert_prices(rows)
    assert float(db.query("SELECT close_price FROM market_daily_prices WHERE trade_date='2024-11-05'")[0][0]) == 1020.0
    assert market_data.upsert_prices([]) == 0
    assert market_data.upsert_index('TAIEX_TR', [(date(2024, 11, 5), 50000.5), (date(2024, 11, 6), None)]) == 1
    assert db.query("SELECT symbol, close_price FROM index_daily_prices")[0] == ('TAIEX_TR', 50000.5)


@pytest.mark.db
def test_rebuild_adj_scales_history_before_ex_date(clean_db):
    """除息 10 元、前收 100 → 參考價 90：事件前的歷史 × 0.9，事件日起等於收盤；沒有事件的股票 adj = close。"""
    import market_data
    db = clean_db
    market_universe.upsert([{'stock_id': '1101', 'stock_name': '台泥', 'market_type': 'twse', 'industry_type': '水泥工業', 'listing_date': None, 'delisted_date': None},
                            {'stock_id': '2330', 'stock_name': '台積電', 'market_type': 'twse', 'industry_type': '半導體業', 'listing_date': None, 'delisted_date': None}])
    market_data.upsert_prices([
        {'stock_id': '1101', 'trade_date': date(2024, 6, 28), 'close_price': 100.0, 'source': 'twse'},
        {'stock_id': '1101', 'trade_date': date(2024, 7, 1), 'close_price': 90.0, 'source': 'twse'},   # 除息日
        {'stock_id': '1101', 'trade_date': date(2024, 7, 2), 'close_price': 91.0, 'source': 'twse'},
        {'stock_id': '2330', 'trade_date': date(2024, 7, 1), 'close_price': 1000.0, 'source': 'twse'},
    ])
    db.execute("""INSERT INTO stock_dividend_result (stock_id, ex_date, before_price, reference_price, dividend, dividend_type)
                  VALUES ('1101', '2024-07-01', 100, 90, 10, '息')""")
    n = market_data.rebuild_adj()
    assert n == 4
    adj = {d: float(a) for d, a in db.query("SELECT trade_date, adj_close FROM market_daily_prices WHERE stock_id='1101' ORDER BY 1")}
    assert adj[date(2024, 6, 28)] == pytest.approx(90.0)            # 100 × 0.9
    assert adj[date(2024, 7, 1)] == 90.0 and adj[date(2024, 7, 2)] == 91.0
    # 跨除息日的報酬：用 adj 是 0%，用 close 是 −10% 的假跌
    assert adj[date(2024, 7, 1)] / adj[date(2024, 6, 28)] == pytest.approx(1.0)
    assert float(db.query("SELECT adj_close FROM market_daily_prices WHERE stock_id='2330'")[0][0]) == 1000.0
    assert market_data.rebuild_adj() == 0                             # 重跑：沒有列需要改


@pytest.mark.db
def test_checks_report_shape_and_survivorship(clean_db):
    import market_data
    market_universe.upsert([{'stock_id': '2311', 'stock_name': '日月光', 'market_type': None, 'industry_type': None, 'listing_date': None, 'delisted_date': date(2018, 4, 30)},
                            {'stock_id': '2330', 'stock_name': '台積電', 'market_type': 'twse', 'industry_type': '半導體業', 'listing_date': None, 'delisted_date': None}])
    market_data.upsert_prices([{'stock_id': '2311', 'trade_date': date(2018, 1, 2), 'close_price': 38.3, 'source': 'finmind'},
                               {'stock_id': '2330', 'trade_date': date(2018, 1, 2), 'close_price': 232.5, 'source': 'finmind'}])
    out = {c['check']: c for c in market_data.checks(date(2018, 1, 1))}
    assert {'survivorship', 'day_coverage', 'adj_close_null', 'tracked_consistency', 'limit_lock_share', 'revenue_coverage', 'benchmark_index'} <= set(out)
    assert out['survivorship']['ok'] is True and out['survivorship']['value'] == '1/1'    # 下市股有價格
    assert out['adj_close_null']['ok'] is False and out['adj_close_null']['value'] == 2    # 還沒 rebuild
    assert out['benchmark_index']['ok'] is False                                          # 還沒有 TAIEX_TR
    market_data.rebuild_adj()
    assert {c['check']: c for c in market_data.checks(date(2018, 1, 1))}['adj_close_null']['ok'] is True


@pytest.mark.db
def test_pending_ids_skips_delisted_before_start_and_covered(clean_db):
    import market_data
    market_universe.upsert([
        {'stock_id': '2311', 'stock_name': 'a', 'market_type': None, 'industry_type': None, 'listing_date': None, 'delisted_date': date(2017, 4, 30)},
        {'stock_id': '2330', 'stock_name': 'b', 'market_type': 'twse', 'industry_type': None, 'listing_date': None, 'delisted_date': None},
        {'stock_id': '3373', 'stock_name': 'c', 'market_type': 'tpex', 'industry_type': None, 'listing_date': None, 'delisted_date': date(2024, 7, 1)},
        {'stock_id': '6999', 'stock_name': 'd', 'market_type': 'tpex', 'industry_type': None, 'listing_date': date(2030, 1, 1), 'delisted_date': None},
    ])
    market_data.upsert_prices([{'stock_id': '3373', 'trade_date': date(2024, 6, 28), 'close_price': 1.0, 'source': 'finmind'}])
    end = date(2026, 10, 7)
    assert market_data.pending_ids(date(2018, 1, 1), end) == ['2330']      # 2311 在起點前下市；3373 已補到下市日前；6999 還沒上市
