"""追蹤股三張表從全市場表補齊（Iteration 83）：只補缺的列、FinMind 已寫的列不動、漲跌 NULL 用前一日收盤算回來、補到行情或窗口內有公司行動的股票重建 adj_close。"""
from datetime import date

import pytest


@pytest.mark.db
def test_fill_from_market_only_missing_rows_and_rebuilds_adj(clean_db):
    import tracked_sync

    db = clean_db
    db.seed_stock('2454', '聯發科')
    db.seed_stock('2330', '台積電')
    db.seed_stock('9999', '不追蹤', tracking=False)
    db.seed_stock('2409', '友達')          # 沒有缺列，但窗口內除息 → 也要重建
    db.seed_prices('2409', [date(2024, 1, 2), date(2024, 1, 3)], close=20, step=1)
    db.execute("""INSERT INTO stock_dividend_result (stock_id, ex_date, before_price, reference_price, dividend, dividend_type)
                  VALUES ('2409', '2024-01-03', 20, 19, 1, 'cash')""")
    # FinMind 已寫的列：2330 兩天（成交量故意和交易所檔不同，驗證不被覆蓋）
    db.seed_prices('2330', [date(2024, 1, 2), date(2024, 1, 3)], close=600, step=10)
    db.execute("UPDATE stock_daily_prices SET volume = 111 WHERE stock_id = '2330'")
    for sid, d, c, chg in (('2454', date(2023, 12, 29), 1000, 10), ('2454', date(2024, 1, 2), 1010, None), ('2454', date(2024, 1, 3), 1030, 20),
                           ('2330', date(2024, 1, 2), 600, 5), ('2330', date(2024, 1, 3), 610, 10), ('2330', date(2024, 1, 4), 620, 10),
                           ('9999', date(2024, 1, 3), 50, 1)):
        db.execute("""INSERT INTO market_daily_prices (stock_id, trade_date, open_price, high_price, low_price, close_price, volume, turnover_value, transaction_count, change_value, source)
                      VALUES (%s, %s, %s, %s, %s, %s, 999, 1, 1, %s, 'twse')""", (sid, d, c, c, c, c, chg))
    db.execute("""INSERT INTO market_institutional_daily (stock_id, trade_date, foreign_buy, foreign_sell, foreign_net, trust_buy, trust_sell, trust_net, dealer_buy, dealer_sell, dealer_net, total_net, source)
                  VALUES ('2454', '2024-01-03', 10, 4, 6, 2, 1, 1, 0, 1, -1, 6, 'twse')""")
    db.execute("""INSERT INTO market_foreign_holding_daily (stock_id, trade_date, shares_issued, foreign_shares, foreign_ratio, source)
                  VALUES ('2454', '2024-01-03', 1000, 300, 30.0, 'twse')""")
    # 2454 在 2024-01-03 除息 10 元：前一日 adj_close 要被縮到 1010 × (1020/1030)
    db.execute("""INSERT INTO stock_dividend_result (stock_id, ex_date, before_price, reference_price, dividend, dividend_type)
                  VALUES ('2454', '2024-01-03', 1030, 1020, 10, 'cash')""")

    r = tracked_sync.fill_from_market(since=date(2024, 1, 1))

    assert r['stock_ids'] == ['2330', '2409', '2454'] and r['prices'] == 3 and r['chips'] == 1 and r['holding'] == 1
    rows = db.query("SELECT stock_id, trade_date, close_price, volume, change_value, change_rate, adj_close FROM stock_daily_prices ORDER BY 1, 2")
    by = {(r[0], r[1]): r[2:] for r in rows}
    assert set(by) == {('2330', date(2024, 1, 2)), ('2330', date(2024, 1, 3)), ('2330', date(2024, 1, 4)), ('2454', date(2024, 1, 2)), ('2454', date(2024, 1, 3)),
                       ('2409', date(2024, 1, 2)), ('2409', date(2024, 1, 3))}
    assert abs(float(by[('2409', date(2024, 1, 2))][4]) - 20 * 19 / 20) < 0.01 and float(by[('2409', date(2024, 1, 3))][4]) == 21   # 沒缺列也重建
    assert by[('2330', date(2024, 1, 2))][1] == 111                                   # FinMind 的列沒被覆蓋
    assert by[('2330', date(2024, 1, 4))][1] == 999 and float(by[('2330', date(2024, 1, 4))][3]) == 1.639   # 10 / 610
    assert float(by[('2454', date(2024, 1, 2))][2]) == 10 and float(by[('2454', date(2024, 1, 2))][3]) == 1.0   # 漲跌 NULL → 1010 − 1000（since 之前那天只拿來算差）
    assert float(by[('2454', date(2024, 1, 3))][4]) == 1030 and abs(float(by[('2454', date(2024, 1, 2))][4]) - 1010 * 1020 / 1030) < 0.01
    assert db.query("SELECT foreign_investor_buy, investment_trust_buy, dealer_buy, total_net_buy FROM stock_chip_analysis") == [(6, 1, -1, 6)]
    assert db.query("SELECT foreign_shares, shares_issued FROM stock_foreign_holding") == [(300, 1000)]
    assert db.query("SELECT count(*) FROM stock_daily_prices WHERE stock_id = '9999'") == [(0,)]   # 不追蹤的不補

    again = tracked_sync.fill_from_market(since=date(2024, 1, 1))
    assert (again['prices'], again['chips'], again['holding'], again['stock_ids']) == (0, 0, 0, ['2409', '2454'])   # 冪等；窗口內有事件的仍重建
