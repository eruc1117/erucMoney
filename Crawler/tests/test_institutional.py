"""三大法人買賣超解析（Iteration 71）：證交所 T86 19 欄、櫃買 16 欄與 24 欄、休市、合計不等時擋下。"""
from datetime import date

import pytest

from scrapers import exchange_daily as ex


TWSE_FIELDS = ['證券代號', '證券名稱', '外陸資買進股數(不含外資自營商)', '外陸資賣出股數(不含外資自營商)', '外陸資買賣超股數(不含外資自營商)',
               '外資自營商買進股數', '外資自營商賣出股數', '外資自營商買賣超股數', '投信買進股數', '投信賣出股數', '投信買賣超股數',
               '自營商買賣超股數', '自營商買進股數(自行買賣)', '自營商賣出股數(自行買賣)', '自營商買賣超股數(自行買賣)',
               '自營商買進股數(避險)', '自營商賣出股數(避險)', '自營商買賣超股數(避險)', '三大法人買賣超股數']


def _twse(data, stat='OK'):
    return {'stat': stat, 'date': '20240102', 'fields': TWSE_FIELDS, 'data': data}


def test_parse_twse_t86_sums_foreign_dealer_and_dealer_legs():
    row = ['2618', '長榮航          ', '163,559,764', '34,581,802', '128,977,962', '1,000', '500', '500',
           '11,656,305', '0', '11,656,305', '10,114,608', '5,167,498', '2,180,000', '2,987,498', '8,227,110', '1,100,000', '7,127,110',
           '150,749,375']
    rows = ex.parse_twse_institutional(_twse([row]))
    assert len(rows) == 1
    r = rows[0]
    assert r['stock_id'] == '2618' and r['trade_date'] == date(2024, 1, 2) and r['source'] == 'twse'
    assert r['foreign_buy'] == 163_559_764 + 1_000 and r['foreign_sell'] == 34_581_802 + 500 and r['foreign_net'] == 128_977_962 + 500
    assert r['trust_net'] == 11_656_305 and r['dealer_net'] == 10_114_608
    assert r['dealer_buy'] == 5_167_498 + 8_227_110 and r['dealer_sell'] == 2_180_000 + 1_100_000
    assert r['total_net'] == 150_749_375 == r['foreign_net'] + r['trust_net'] + r['dealer_net']


def test_parse_twse_holiday_and_format_guard():
    assert ex.parse_twse_institutional({'stat': '很抱歉，沒有符合條件的資料!'}) == []
    assert ex.parse_twse_institutional(_twse([])) == []
    # 合計欄對不上（像是欄位順序變了）→ 擋下
    bad = ['2330', '台積電', '10', '0', '10', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '999']
    with pytest.raises(ex.ExchangeFormatError):
        ex.parse_twse_institutional(_twse([bad]))
    # 欄位名不認得 → 擋下，不會猜
    p = _twse([bad])
    p['fields'] = [f.replace('三大法人買賣超股數', '合計') for f in TWSE_FIELDS]
    with pytest.raises(ex.ExchangeFormatError):
        ex.parse_twse_institutional(p)


def test_parse_tpex_16_columns_2018_layout():
    fields = ['代號', '名稱', '外資及陸資買股數', '外資及陸資賣股數', '外資及陸資淨買股數', '投信買進股數', '投信賣股數', '投信淨買股數',
              '自營淨買股數', '自營商(自行買賣)買股數', '自營商(自行買賣)賣股數', '自營商(自行買賣)淨買股數', '自營商(避險)買股數',
              '自營商(避險)賣股數', '自營商(避險)淨買股數', '三大法人買賣超股數']
    data = [['5483', '中美晶', '1,200,000', '200,000', '1,000,000', '50,000', '0', '50,000', '-30,000', '10,000', '20,000', '-10,000',
             '0', '20,000', '-20,000', '1,020,000']]
    rows = ex.parse_tpex_institutional({'tables': [{}, {'date': '107/01/03', 'fields': fields, 'data': data}]})
    r = rows[0]
    assert r['trade_date'] == date(2018, 1, 3) and r['source'] == 'tpex'
    assert (r['foreign_buy'], r['foreign_sell'], r['foreign_net']) == (1_200_000, 200_000, 1_000_000)
    assert (r['trust_net'], r['dealer_net'], r['total_net']) == (50_000, -30_000, 1_020_000)
    assert r['dealer_buy'] == 10_000 and r['dealer_sell'] == 40_000


def test_parse_tpex_24_columns_positional_layout_and_holiday():
    fields = ['代號', '名稱'] + ['買進股數', '賣出股數', '買賣超股數'] * 7 + ['三大法人買賣超股數合計']
    # 006201 那列是 2024-01-02 的真實列：外資合計 (0, 6000, −6000)、自營合計 (1000, 7112, −6112)、總計 −12112
    data = [['006201', '元大富櫃50', '0', '6,000', '-6,000', '0', '0', '0', '0', '6,000', '-6,000', '0', '0', '0', '0', '0', '0',
             '1,000', '7,112', '-6,112', '1,000', '7,112', '-6,112', '-12,112']]
    rows = ex.parse_tpex_institutional({'tables': [{'date': '113/01/02', 'fields': fields, 'data': data}]})
    r = rows[0]
    assert r['trade_date'] == date(2024, 1, 2)
    assert (r['foreign_buy'], r['foreign_sell'], r['foreign_net']) == (0, 6_000, -6_000)
    assert (r['trust_net'], r['dealer_buy'], r['dealer_sell'], r['dealer_net'], r['total_net']) == (0, 1_000, 7_112, -6_112, -12_112)
    assert ex.parse_tpex_institutional({'tables': [{'date': '113/01/01', 'fields': fields, 'data': []}]}) == []
    with pytest.raises(ex.ExchangeFormatError):
        ex.parse_tpex_institutional({'tables': [{'date': '113/01/02', 'fields': fields[:20], 'data': data}]})
