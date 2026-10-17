"""個股估值解析（Iteration 78）：證交所 BWIBBU_d 8 欄、櫃買 peQryDate 7 欄、虧損「-」／N/A → None、休市、欄位名變了擋下。"""
from datetime import date

import pytest

from scrapers import exchange_daily as ex


TWSE_FIELDS = ['證券代號', '證券名稱', '收盤價', '殖利率(%)', '股利年度', '本益比', '股價淨值比', '財報年/季']
TPEX_FIELDS = ['股票代號', '公司名稱', '本益比', '每股股利', '股利年度', '殖利率(%)', '股價淨值比']


def test_parse_twse_bwibbu_by_field_name_and_loss_dash():
    payload = {'stat': 'OK', 'date': '20240102', 'fields': TWSE_FIELDS,
               'data': [['1101', '台泥', '34.70', '1.44', 111, '29.41', '1.14', '112/3'],
                        ['1213', '大飲', '6.99', '0.00', 111, '-', '1.47', '112/3'],
                        ['', '', '', '', '', '', '', '']]}
    rows = ex.parse_twse_valuation(payload)
    assert [r['stock_id'] for r in rows] == ['1101', '1213']
    r = rows[0]
    assert r['trade_date'] == date(2024, 1, 2) and r['source'] == 'twse'
    assert (r['close_price'], r['dividend_yield'], r['pe'], r['pb']) == (34.70, 1.44, 29.41, 1.14)
    assert r['dividend_year'] == 111 and r['fin_period'] == '112/3' and r['dividend_per_share'] is None
    assert rows[1]['pe'] is None and rows[1]['pb'] == 1.47                      # 虧損印「-」→ None，其他欄照存


def test_parse_twse_holiday_and_field_guard():
    assert ex.parse_twse_valuation({'stat': '很抱歉，沒有符合條件的資料!', 'total': 0}) == []
    p = {'stat': 'OK', 'date': '20240102', 'fields': [f.replace('股價淨值比', 'PBR') for f in TWSE_FIELDS],
         'data': [['1101', '台泥', '34.70', '1.44', 111, '29.41', '1.14', '112/3']]}
    with pytest.raises(ex.ExchangeFormatError):
        ex.parse_twse_valuation(p)
    # 股價淨值比欄大多不是正數 → 欄位對錯了，擋下
    p2 = {'stat': 'OK', 'date': '20240102', 'fields': TWSE_FIELDS,
          'data': [['1101', '台泥', '34.70', '1.44', 111, '29.41', '-', '112/3'], ['1102', '亞泥', '41.15', '5.59', 111, '14.34', '-', '112/3']]}
    with pytest.raises(ex.ExchangeFormatError):
        ex.parse_twse_valuation(p2)


def test_parse_tpex_pe_by_field_name_na_and_holiday():
    payload = {'tables': [{'date': '107/01/02', 'totalCount': 2, 'fields': TPEX_FIELDS,
                           'data': [['1258', '其祥-KY         ', '16.51', '0.50000000', 106, '4.28', '1.31'],
                                    ['1333', '恩得利          ', 'N/A', '0.00000000', 106, '0.00', '0.85']]}]}
    rows = ex.parse_tpex_valuation(payload)
    assert len(rows) == 2
    r = rows[0]
    assert r['trade_date'] == date(2018, 1, 2) and r['source'] == 'tpex' and r['close_price'] is None and r['fin_period'] is None
    assert (r['pe'], r['dividend_per_share'], r['dividend_year'], r['dividend_yield'], r['pb']) == (16.51, 0.5, 106, 4.28, 1.31)
    assert rows[1]['pe'] is None and rows[1]['dividend_yield'] == 0.0
    assert ex.parse_tpex_valuation({'tables': [{'date': '113/01/01', 'totalCount': 0, 'fields': TPEX_FIELDS, 'data': []}]}) == []
    bad = {'tables': [{'date': '107/01/02', 'fields': [f.replace('殖利率(%)', '殖利率') for f in TPEX_FIELDS], 'data': payload['tables'][0]['data']}]}
    with pytest.raises(ex.ExchangeFormatError):
        ex.parse_tpex_valuation(bad)
