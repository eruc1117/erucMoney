"""紙上交易（Iteration 54，階段 4）：訊號日判定、開盤成交（零股、成本、鎖死不成交、現金不足縮單）、結算對 0050、補跑、檢討。測試庫。"""
from datetime import date

import pytest

import portfolio_paper as pp

pytestmark = pytest.mark.db

DAYS = [date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 15)]   # 10/10 國慶、11-12 週末


def _seed_market(db, closes: dict, lock: dict = None):
    """closes = {stock: [close per DAYS]}；open = close × 0.99、high = close × 1.01、low = close × 0.98；lock 指定某天一字鎖漲停。
    每天多塞 600 檔假股票，讓 market_days 把那天當成有全市場行情。"""
    rows = []
    for sid, cs in closes.items():
        for d, c in zip(DAYS, cs):
            if lock and lock.get(sid) == d:
                prev = closes[sid][DAYS.index(d) - 1]
                o = h = l = c = round(prev * 1.1, 2)
            else:
                o, h, l = round(c * 0.99, 2), round(c * 1.01, 2), round(c * 0.98, 2)
            rows.append((sid, d, o, h, l, c))
    for d in DAYS:
        rows += [(f'9{i:04d}', d, 10.0, 10.0, 10.0, 10.0) for i in range(600)]
    from psycopg2.extras import execute_values
    from db.connection import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, "INSERT INTO market_daily_prices (stock_id, trade_date, open_price, high_price, low_price, close_price, adj_close, source) VALUES %s",
                           [(s, d, o, h, l, c, c, 'test') for s, d, o, h, l, c in rows], page_size=2000)
            execute_values(cur, "INSERT INTO stock_daily_prices (stock_id, trade_date, close_price, adj_close) VALUES %s",
                           [('0050', d, 100.0 + i, 100.0 + i) for i, d in enumerate(DAYS)])
        conn.commit()


def _seed_list(db, rd: date, weights: dict):
    for i, (sid, w) in enumerate(weights.items(), 1):
        db.execute("INSERT INTO portfolio_live_list (run_id, rebalance_date, exec_date, stock_id, stock_name, rank, target_weight) VALUES (NULL, %s, NULL, %s, %s, %s, %s)",
                   (rd, sid, sid, None if sid == '2330' else i, w))


def test_signal_date_is_first_market_day_on_or_after_11th(clean_db):
    _seed_market(clean_db, {'1111': [100] * 5})
    assert pp.signal_date_for_month(2026, 10, date(2026, 10, 9)) is None            # 還沒到 11 日
    assert pp.signal_date_for_month(2026, 10, date(2026, 10, 13)) == date(2026, 10, 13)
    assert pp.signal_date_for_month(2026, 10, date(2026, 10, 15)) == date(2026, 10, 13)
    assert pp.market_days(date(2026, 10, 1), date(2026, 10, 31)) == DAYS


def test_start_once_then_fill_mark_review(clean_db, monkeypatch):
    db = clean_db
    _seed_market(db, {'1111': [100, 100, 100, 100, 110], '2222': [50, 50, 50, 50, 45], '2330': [1000, 1000, 1000, 1000, 1000]})
    st = pp.start(capital=1_000_000, run_id=None, started_on=date(2026, 10, 9))
    assert st['cash'] == 1_000_000
    with pytest.raises(RuntimeError):
        pp.start()
    # 10/13 的清單：台積電 0.5、1111 0.25、2222 0.25；10/14 開盤成交
    _seed_list(db, date(2026, 10, 13), {'2330': 0.5, '1111': 0.25, '2222': 0.25})
    monkeypatch.setattr(pp, 'make_list', lambda rd, run_id: {'n': 0, 'new': []})     # 不跑真的回測
    r = pp.run_daily(date(2026, 10, 14))
    assert len(r['filled']) == 1 and r['filled'][0]['exec_date'] == date(2026, 10, 14) and r['filled'][0]['buys'] == 3
    held = pp.holdings()
    # 開盤價 = 收盤 × 0.99；買單按比例縮以留手續費：股數 = floor(權重 × 資金 ÷ (1 + 手續費) ÷ 開盤價)
    import math
    exp = {s: math.floor(w * 1_000_000 / (1 + pp.FEE_RATE) / o) for s, w, o in (('2330', 0.5, 990), ('1111', 0.25, 99), ('2222', 0.25, 49.5))}
    assert held == exp == {'2330': 504, '1111': 2523, '2222': 5046}
    cash = pp.state()['cash']
    gross = {s: n * o for s, n, o in (('2330', held['2330'], 990), ('1111', held['1111'], 99), ('2222', held['2222'], 49.5))}
    assert cash == pytest.approx(1_000_000 - sum(gross.values()) - sum(round(g * pp.FEE_RATE, 2) for g in gross.values()), abs=0.05)
    # 結算：10/9、10/13 全現金 = 100 萬；10/14 用收盤
    navs = {str(d): float(n) for d, n in db.query('SELECT trade_date, nav FROM portfolio_paper_nav ORDER BY 1')}
    assert navs['2026-10-09'] == 1_000_000 and navs['2026-10-13'] == 1_000_000
    assert navs['2026-10-14'] == pytest.approx(cash + held['2330'] * 1000 + held['1111'] * 100 + held['2222'] * 50, abs=0.05)
    # 再跑一天：不重複成交、補結算 10/15
    r2 = pp.run_daily(date(2026, 10, 15))
    assert r2['filled'] == [] and r2['marked'] == 1
    rv = pp.review()
    assert rv['days'] == 4 and rv['n_holdings'] == 3 and rv['bench_return'] == pytest.approx(104 / 101 - 1, abs=1e-4)   # 0050 從起始日 10/9 的 101 → 104
    assert rv['port_return'] == pytest.approx((cash + held['2330'] * 1000 + held['1111'] * 110 + held['2222'] * 45) / 1_000_000 - 1, abs=1e-6)
    assert rv['monthly'][0]['month'] == '2026-10' and rv['monthly'][0]['active'] == pytest.approx(rv['port_return'] - rv['bench_return'], abs=1e-6)


def test_fill_skips_locked_and_sells_dropped_names(clean_db, monkeypatch):
    db = clean_db
    _seed_market(db, {'1111': [100] * 5, '2222': [50] * 5, '3333': [20, 20, 20, 20, 20]}, lock={'3333': date(2026, 10, 14)})
    pp.start(capital=100_000, run_id=None, started_on=date(2026, 10, 9))
    _seed_list(db, date(2026, 10, 8), {'1111': 0.5, '2222': 0.5})            # 第一份清單 10/9 成交
    monkeypatch.setattr(pp, 'make_list', lambda rd, run_id: {'n': 0, 'new': []})
    pp.run_daily(date(2026, 10, 9))
    assert pp.holdings() == {'1111': 504, '2222': 1009}                         # 留手續費後取整
    # 第二份清單 10/13：1111 不要了、3333 進來（但 10/14 一字鎖漲停 → 不成交）
    _seed_list(db, date(2026, 10, 13), {'2222': 0.5, '3333': 0.5})
    r = pp.run_daily(date(2026, 10, 14))
    f = r['filled'][0]
    assert f['sells'] == 1 and f['unfilled'] == ['3333']
    assert pp.holdings() == {'2222': 1009}                                       # 1111 全賣、3333 沒成交、現金留著
    rows = db.query("SELECT stock_id, side, filled, note FROM portfolio_paper_trades WHERE rebalance_date = '2026-10-13' ORDER BY stock_id")
    assert ('3333', 'buy', False, '一字鎖死未成交') in rows and ('1111', 'sell', True, None) in rows
    sell = db.query("SELECT gross, fee, tax FROM portfolio_paper_trades WHERE stock_id = '1111' AND side = 'sell'")[0]
    assert float(sell[2]) == pytest.approx(float(sell[0]) * pp.TAX_RATE, abs=0.01)     # 賣出有證交稅
    assert pp.pending_lists(date(2026, 10, 20)) == []                             # 兩份都處理過了


def test_run_daily_without_account_or_data(clean_db):
    assert 'skipped' in pp.run_daily(date(2026, 10, 9))
    pp.start(capital=1, run_id=None, started_on=date(2026, 10, 9))
    assert pp.run_daily(date(2026, 10, 9)).get('skipped')                        # 沒行情
    assert pp.review()['days'] == 0
