"""融資融券／借券與外資持股解析（Iteration 81）：證交所 MI_MARGN 16 欄按位置、TWT93U 15 欄、櫃買兩表、張 → 股、對位檢查、休市、欄位變了擋下。"""
from datetime import date

import pytest

from scrapers import exchange_daily as ex


MARGN_FIELDS = ['代號', '名稱', '買進', '賣出', '現金償還', '前日餘額', '今日餘額', '次一營業日限額', '買進', '賣出', '現券償還', '前日餘額', '今日餘額', '次一營業日限額', '資券互抵', '註記']
TWT93U_FIELDS = ['代號', '名稱', '前日餘額', '賣出', '買進', '現券', '今日餘額', '次一營業日限額', '前日餘額', '當日賣出', '當日還券', '當日調整', '當日餘額', '次一營業日可限額', '備註']
TPEX_MARGIN_FIELDS = ['代號', '名稱', '前資餘額(張)', '資買', '資賣', '現償', '資餘額', '資屬證金', '資使用率(%)', '資限額', '前券餘額(張)', '券賣', '券買', '券償', '券餘額',
                      '券屬證金', '券使用率(%)', '券限額', '資券相抵(張)', '備註']
TPEX_SBL_FIELDS = ['股票代號', '股票名稱', '前日餘額', '賣出', '買進', '現券', '當日餘額', '限額', '前日餘額', '當日賣出', '當日還券', '當日調整數額', '當日餘額', '次一營業日可借券賣出限額', '備註']


def _margn(data, stat='OK'):
    return {'stat': stat, 'date': '20240102', 'tables': [{'title': '信用交易統計', 'fields': [], 'data': []},
                                                        {'title': '113年01月02日 融資融券彙總 (全部)', 'fields': MARGN_FIELDS, 'data': data}]}


def test_parse_twse_margin_positional_lots_to_shares_and_guard():
    row = ['2330', '台積電', '310', '513', '10', '13,057', '12,844', '6,483,017', '2', '21', '0', '189', '208', '6,483,017', '1', ' ']
    rows = ex.parse_twse_margin(_margn([row]))
    r = rows[0]
    assert r['trade_date'] == date(2024, 1, 2) and r['source'] == 'twse'
    assert (r['margin_buy'], r['margin_sell'], r['margin_balance']) == (310_000, 513_000, 12_844_000)
    assert (r['short_buy'], r['short_sell'], r['short_balance']) == (2_000, 21_000, 208_000)
    assert ex.parse_twse_margin({'stat': '很抱歉，沒有符合條件的資料!'}) == []
    bad = _margn([row])
    bad['tables'][1]['fields'] = MARGN_FIELDS[:15]
    with pytest.raises(ex.ExchangeFormatError):
        ex.parse_twse_margin(bad)


def test_parse_twse_sbl_and_merge_identity_check():
    sbl = {'stat': 'OK', 'date': '20240102', 'fields': TWT93U_FIELDS,
           'data': [['2330', '台積電', '189,000', '21,000', '2,000', '0', '208,000', '6,483,017,748', '9,302,665', '626,000', '96,000', '0', '9,832,665', '8,572,948', ' ']]}
    s = ex.parse_twse_sbl(sbl)
    assert s[0]['short_balance_chk'] == 208_000 and s[0]['sbl_sell'] == 626_000 and s[0]['sbl_balance'] == 9_832_665
    m = ex.parse_twse_margin(_margn([['2330', '台積電', '310', '513', '10', '13,057', '12,844', '6,483,017', '2', '21', '0', '189', '208', '6,483,017', '1', ' '],
                                     ['1101', '台泥', '1', '1', '0', '10', '10', '100', '0', '0', '0', '0', '0', '100', '0', ' ']]))
    merged = ex.merge_margin_sbl(m, s, 'test')
    assert merged[0]['sbl_balance'] == 9_832_665 and merged[1]['sbl_balance'] is None      # 借券表沒列的股票借券欄留空
    # 融券餘額對不上 → 擋下
    s2 = ex.parse_twse_sbl({**sbl, 'data': [sbl['data'][0][:6] + ['999,000'] + sbl['data'][0][7:]]})
    with pytest.raises(ex.ExchangeFormatError):
        ex.merge_margin_sbl(ex.parse_twse_margin(_margn([m and ['2330', '台積電', '310', '513', '10', '13,057', '12,844', '6,483,017', '2', '21', '0', '189', '208', '6,483,017', '1', ' ']])), s2, 'test')
    with pytest.raises(ex.ExchangeFormatError):
        ex.parse_twse_sbl({**sbl, 'fields': TWT93U_FIELDS[:14]})


def test_parse_tpex_margin_and_sbl_by_name_and_position():
    pay = {'date': '20240102', 'tables': [{'title': '上櫃股票融資融券餘額', 'date': '113/01/02', 'fields': TPEX_MARGIN_FIELDS,
           'data': [['5483', '中美晶', '6,624', '127', '298', '0', '6,453', '48', '4.4', '146,555', '285', '219', '5', '0', '499', '0', '0.34', '146,555', '1', '']]}]}
    r = ex.parse_tpex_margin(pay)[0]
    assert r['trade_date'] == date(2024, 1, 2) and r['source'] == 'tpex'
    assert (r['margin_buy'], r['margin_sell'], r['margin_balance'], r['short_sell'], r['short_buy'], r['short_balance']) == (127_000, 298_000, 6_453_000, 219_000, 5_000, 499_000)
    sbl = {'date': '20240102', 'tables': [{'title': '信用額度總量管制餘額表', 'date': '113/01/02', 'fields': TPEX_SBL_FIELDS,
           'data': [['5483', '中美晶', '480,000', '20,000', '1,000', '0', '499,000', '146,555,000', '1,000,000', '50,000', '0', '0', '1,050,000', '9,999', '']]}]}
    s = ex.parse_tpex_sbl(sbl)
    assert s[0]['short_balance_chk'] == 499_000 and s[0]['sbl_balance'] == 1_050_000 and s[0]['sbl_sell'] == 50_000
    assert ex.merge_margin_sbl(ex.parse_tpex_margin(pay), s, 'test')[0]['sbl_balance'] == 1_050_000
    assert ex.parse_tpex_margin({'date': '20240101', 'tables': [{'date': '113/01/01', 'fields': TPEX_MARGIN_FIELDS, 'data': []}]}) == []
    with pytest.raises(ex.ExchangeFormatError):
        ex.parse_tpex_margin({'date': '20240102', 'tables': [{'date': '113/01/02', 'fields': [f.replace('券餘額', '融券餘額') for f in TPEX_MARGIN_FIELDS],
                                                             'data': pay['tables'][0]['data']}]})


def test_parse_holding_both_exchanges_with_ratio_check():
    tw = {'stat': 'OK', 'date': '20240102', 'fields': ['證券代號', '證券名稱', '國際證券編碼', '發行股數', '外資及陸資尚可投資股數', '全體外資及陸資持有股數',
                                                      '外資及陸資尚可投資比率', '全體外資及陸資持股比率', '外資及陸資共用法令投資上限比率', '陸資法令投資上限比率', '與前日異動原因(註)', '最近一次上市公司申報外資及陸資持股異動日期'],
          'data': [['2330', '台積電', 'TW0002330008', '25,932,070,992', '6,979,966,613', '18,952,104,379', 26.91, 73.08, '100.00', '100.00', '', '112/05/22']]}
    r = ex.parse_twse_holding(tw)[0]
    assert r['shares_issued'] == 25_932_070_992 and r['foreign_shares'] == 18_952_104_379 and r['foreign_ratio'] == pytest.approx(73.08, abs=0.01)
    tp = {'tables': [{'date': '113/01/02', 'fields': ['排行', '代號', '名稱', '發行股數(A)', '僑外資及陸資尚可投資股數B=A*F-C', '僑外資及陸資持有股數(C)',
                                                      '僑外資及陸資尚可投資比率(D=B/A)', '僑外資及陸資持股比率(E=C/A)', '法令投資上限比率(F)', '備註'],
                      'data': [['85', '5483', '中美晶', '586,221,651', '473,549,376', '112,672,275', '80.78%', '19.22%', '100%', '']]}]}
    r2 = ex.parse_tpex_holding(tp)[0]
    assert r2['stock_id'] == '5483' and r2['source'] == 'tpex' and r2['foreign_ratio'] == pytest.approx(19.22, abs=0.01)
    assert ex.parse_twse_holding({'stat': '很抱歉，沒有符合條件的資料!'}) == []
    bad = {**tw, 'data': [tw['data'][0][:7] + [50.0] + tw['data'][0][8:]]}       # 比率和股數對不上 → 擋下
    with pytest.raises(ex.ExchangeFormatError):
        ex.parse_twse_holding(bad)


def test_drop_transfer_duplicates_keeps_tpex_row_on_transfer_day():
    # 2019-12-13 美時 1795 轉上市：證交所列 59,000 股（佔位）、櫃買列 167,578,276 股（實際）；同一批 upsert 會撞 (stock_id, trade_date)
    tw = [{'stock_id': '1795', 'source': 'twse', 'foreign_shares': 59_000}, {'stock_id': '2330', 'source': 'twse', 'foreign_shares': 1}]
    tp = [{'stock_id': '1795', 'source': 'tpex', 'foreign_shares': 167_578_276}, {'stock_id': '6488', 'source': 'tpex', 'foreign_shares': 2}]
    kept = ex.drop_transfer_duplicates(tw, tp)
    assert [r['stock_id'] for r in kept] == ['2330']
    ids = [r['stock_id'] for r in kept + tp]
    assert len(ids) == len(set(ids)) and next(r for r in kept + tp if r['stock_id'] == '1795')['source'] == 'tpex'
    assert ex.drop_transfer_duplicates(tw, []) == tw
