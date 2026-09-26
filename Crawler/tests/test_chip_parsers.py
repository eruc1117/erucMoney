"""籌碼：三大法人買賣超正負號、自營商合計／子項、外資持股比與上限、持股日期落後行情。"""
import json
from datetime import date

import pandas as pd
import responses

from config import TWSE_API
from helpers.fakes import FakeDataLoader, patch_finmind
from scrapers import twse_scraper
from scrapers.finmind_scraper import FinMindScraper


def _inst_df():
    rows = []
    # 9/22：外資買超、投信買超、自營商用合計 Dealer
    for name, buy, sell in (('Foreign_Investor', 30000000, 17520000), ('Investment_Trust', 1000000, 140000),
                            ('Dealer', 100000, 410000)):
        rows.append({'date': '2026-09-22', 'stock_id': '2330', 'name': name, 'buy': buy, 'sell': sell})
    # 9/23：沒有合計 Dealer，只有 self + Hedging，且外資賣超
    for name, buy, sell in (('Foreign_Investor', 1000, 5500), ('Investment_Trust', 0, 0),
                            ('Dealer_self', 200, 50), ('Dealer_Hedging', 0, 300)):
        rows.append({'date': '2026-09-23', 'stock_id': '2330', 'name': name, 'buy': buy, 'sell': sell})
    return pd.DataFrame(rows)


def test_finmind_chips_net_sign_and_dealer_fallback(monkeypatch):
    patch_finmind(monkeypatch, FakeDataLoader({'taiwan_stock_institutional_investors': _inst_df()}))
    rows = FinMindScraper(['2330'], date(2026, 9, 22)).fetch_chips()
    by = {r.trade_date: r for r in rows}
    a = by[date(2026, 9, 22)]
    assert a.foreign_investor_buy == 12480000 and a.investment_trust_buy == 860000
    assert a.dealer_buy == -310000                       # 合計 Dealer 優先
    assert a.total_net_buy == 12480000 + 860000 - 310000
    assert a.foreign_holding_ratio is None              # 持股比另一支 API
    b = by[date(2026, 9, 23)]
    assert b.foreign_investor_buy == -4500              # 賣超為負
    assert b.dealer_buy == (200 - 50) + (0 - 300)       # 沒有合計 → self + hedging
    assert b.total_net_buy == -4500 + 0 - 150


def test_finmind_chips_empty(monkeypatch):
    patch_finmind(monkeypatch, FakeDataLoader())
    assert FinMindScraper(['2330'], date(2026, 9, 22)).fetch_chips() == []


@responses.activate
def test_twse_t86_signs_and_bad_rows(monkeypatch, fx):
    monkeypatch.setattr(twse_scraper.TWSEScraper, '_random_delay', lambda self: None)
    responses.get(TWSE_API['chip'], json=json.loads(fx('twse_t86.json')))
    rows = twse_scraper.TWSEScraper(['2330'], date(2026, 9, 22)).fetch_chip_analysis(date(2026, 9, 22))
    by = {r.stock_id: r for r in rows}
    assert set(by) == {'2330', '2324'}                  # 壞列被略過
    assert by['2330'].foreign_investor_buy == 12480000 and by['2330'].dealer_buy == -310000
    assert by['2330'].total_net_buy == 13030000
    assert by['2324'].foreign_investor_buy == -4500 and by['2324'].dealer_buy is None    # '--' → None
    assert by['2324'].total_net_buy == -4500


def test_foreign_holding_fields(monkeypatch):
    df = pd.DataFrame([
        {'date': '2026-09-22', 'ForeignInvestmentShares': 17940000000, 'ForeignInvestmentSharesRatio': 69.19,
         'ForeignInvestmentUpperLimitRatio': 100.0, 'NumberOfSharesIssued': 25930000000},
        {'date': '2026-09-19', 'ForeignInvestmentShares': None, 'ForeignInvestmentSharesRatio': float('nan'),
         'ForeignInvestmentUpperLimitRatio': 100.0, 'NumberOfSharesIssued': 25930000000},
    ])
    patch_finmind(monkeypatch, FakeDataLoader({'taiwan_stock_shareholding': df}))
    rows = FinMindScraper(['2330'], date(2026, 9, 19)).fetch_foreign_holding()
    a, b = rows
    assert a.foreign_ratio == 69.19 and a.foreign_upper_limit_ratio == 100.0 and a.foreign_shares == 17940000000
    assert a.foreign_ratio <= a.foreign_upper_limit_ratio
    assert b.foreign_shares is None and b.foreign_ratio is None


def test_holding_date_may_lag_price_date(monkeypatch):
    """
    外資持股統計常比行情晚一天揭露：兩支 API 各自帶自己的日期，抓下來不能互相「對齊」。
    這裡確認 scraper 保留各自日期（落後的判斷交給 Node /stocks 的 foreign_holding_date 與前端 holdingLag）。
    """
    prices = pd.DataFrame([{'date': '2026-09-22', 'open': 1, 'max': 1, 'min': 1, 'close': 100, 'spread': 0,
                            'Trading_Volume': 1, 'Trading_money': 1, 'Trading_turnover': 1}])
    holding = pd.DataFrame([{'date': '2026-09-19', 'ForeignInvestmentShares': 1, 'ForeignInvestmentSharesRatio': 1.0,
                             'ForeignInvestmentUpperLimitRatio': 100.0, 'NumberOfSharesIssued': 10}])
    patch_finmind(monkeypatch, FakeDataLoader({'taiwan_stock_daily': prices, 'taiwan_stock_shareholding': holding}))
    sc = FinMindScraper(['2330'], date(2026, 9, 19), date(2026, 9, 22))
    p = sc.fetch_prices()[0]
    h = sc.fetch_foreign_holding()[0]
    assert h.trade_date < p.trade_date
