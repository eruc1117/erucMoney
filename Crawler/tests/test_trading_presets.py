"""策略範本（Iteration 79）：十種範本合法且金額依資金換算、每種在刻意造的 V 形行情上照定義動作、
合成行情上的比較表結構與可重現、API 兩個端點與 400。全部不連資料庫（get_conn 被攔下）。"""
from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api
import portfolio_paper as pp
import synthetic_market as sm
import trading_presets as tp
import trading_replay as rp
import trading_strategy as st
from helpers import fake_market as fm

CAPITAL = 1_000_000


@pytest.fixture
def no_db(monkeypatch):
    import db.connection as dbc
    for mod in (dbc, pp, rp):
        monkeypatch.setattr(mod, 'get_conn', fm._no_db)


def _buy_amounts(rules):
    return [r['then']['qty'] for r in rules if r['then']['side'] == 'buy']


def test_presets_valid_and_amounts_scale_with_capital():
    assert len(tp.PRESETS) == 10 and len(set(tp.KEYS)) == 10
    start = date(2022, 1, 3)
    for p in tp.PRESETS:
        rules = tp.build(p['key'], ' 2330 ', start, CAPITAL)
        assert st.validate_rules(rules) == [], (p['key'], st.validate_rules(rules))
        assert all(r['stock_id'] == '2330' for r in rules) and p['label'] and p['hint']
        assert tp.START_TOKEN not in str(rules)                                 # '@start' 都換成起始日
        assert _buy_amounts(tp.build(p['key'], '2330', start, 2 * CAPITAL)) == [2 * q for q in _buy_amounts(rules)]
    assert tp.build('buyhold', '2330', start, CAPITAL)[0]['when'] == {'type': 'on_date', 'date': '2022-01-03'}
    assert _buy_amounts(tp.build('buyhold', '2330', start, CAPITAL)) == [500_000]
    lst = tp.list_presets('2454', start, 100_000)
    assert [x['key'] for x in lst] == tp.KEYS and lst[1]['texts'] == ['2454：每月 5 日起第一個交易日 → 買 1500元']
    with pytest.raises(KeyError):
        tp.build('nope', '2330', start, CAPITAL)


def _v_market(start: date, legs: list, bench: float = 100.0) -> dict:
    """刻意造的單檔行情：legs = [(天數, 每日報酬)]，報酬給 'chop' 是 ±0.05% 交錯的盤整；
    開盤 = 收盤（成交就在觸發隔天的收盤價），0050 固定不動。"""
    out, px, prev = {}, 100.0, None
    days = sm.trading_days(start, date(start.year + 3, 12, 31))
    seq = [(0.0005 if i % 2 == 0 else -0.0005) if r == 'chop' else r for n, r in legs for i in range(n)]
    for d, r in zip(days, seq):
        px = round(px * (1 + r), 4)
        out[d] = {'2330': {'open': px, 'high': px, 'low': px, 'close': px, 'prev_close': prev},
                  fm.BENCH: {'open': bench, 'high': bench, 'low': bench, 'close': bench, 'prev_close': bench}}
        prev = px
    return out


def test_each_preset_acts_as_defined_on_v_shaped_market(monkeypatch):
    """跌 60 日（每日 −0.5%）→ 急彈 5 日（每日 +5%）→ 漲 115 日（每日 +0.5%）→ 崩 40 日（每日 −2%）→ 盤整 30 日。
    急彈那 5 天是為了「雙重確認」：慢漲穿過 20 日均線那天 RSI(14) 只有約 40，AND 不成立就永遠不買；急彈後穿線那天 RSI 約 61。"""
    start = date(2021, 1, 4)
    market = _v_market(start, [(60, -0.005), (5, 0.05), (115, 0.005), (40, -0.02), (30, 0.0)])
    fm.patch(monkeypatch, market)
    days = sorted(market)
    end = days[-1]
    t60, t180, t220 = str(days[60]), str(days[180]), str(days[220])        # 各段起點：上漲、崩盤、盤整
    res = {}
    for key in tp.KEYS:
        r = st.simulate_rules(tp.build(key, '2330', start, CAPITAL), start, end, CAPITAL)
        assert r['available'] and r['missing'] == [], key
        fm.check_invariants(r, CAPITAL)
        res[key] = r
    sides = {k: [t['side'] for t in r['trades']] for k, r in res.items()}
    # 買進持有：第一天買一次、從此不動
    assert sides['buyhold'] == ['buy'] and res['buyhold']['trades'][0]['date'] == str(start) and res['buyhold']['final']['holdings']
    # 定期定額：每個月各買一次（期間 250 個交易日跨 12 個月）
    months = {d[:7] for d in (str(x) for x in market)}
    assert sides['dca'] == ['buy'] * len(months) and len(months) == 12
    # 停損停利：第一天買，跌 10%（第 22 天左右）停損賣光、停利從未觸發
    assert sides['stop'] == ['buy', 'sell'] and res['stop']['trades'][1]['pnl'] < 0 and [x['fired'] for x in res['stop']['rules']] == [1, 1, 0]
    assert res['stop']['final']['holdings'] == []
    # 均線進出／季線趨勢：下跌段不會買（價格一直在均線下），上漲段穿過均線買一次，崩盤跌破賣光且有賺（賣價仍高於買價）
    for k in ('ma20', 'ma60'):
        t = res[k]['trades']
        assert sides[k][:2] == ['buy', 'sell'] and t[1]['pnl'] > 0, k
        assert t60 <= t[0]['date'] < t180 <= t[1]['date'] < t220, k                      # 買在上漲段、賣在崩盤段
    # RSI 反轉：Wilder RSI 沒有暖機，連跌第 2 個交易日就是 0 → 第 3 天就買（買得早）；急彈段 RSI > 70 就賣光（賣得早）；在這條 V 上第一趟是賠的——策略本身的性質
    t = res['rsi']['trades']
    assert sides['rsi'][:2] == ['buy', 'sell'] and t[0]['date'] == str(days[2]) and t60 <= t[1]['date'] < t180 and t[1]['pnl'] < 0
    # 動能突破：60 日漲 20% 且在 20 日均線上才買（上漲段後半），崩盤 20 日跌 10% 賣光
    t = res['breakout']['trades']
    assert sides['breakout'][:2] == ['buy', 'sell'] and t60 <= t[0]['date'] < t180 <= t[1]['date'] < t220
    # 雙重確認：長跌後反彈第一天就穿過被拖低的 20 日均線，那天 RSI(14) 才 41.7 < 50，AND 不成立、之後再沒有穿線——整段一筆都不買（會買的情形見下一個測試）
    assert sides['confirm'] == [] and res['confirm']['triggers'] == []
    closes = pd.Series({d: market[d]['2330']['close'] for d in days})
    ind = st._indicators(closes, tp.build('confirm', '2330', start, CAPITAL))
    ma, rsi = ind['ma20'], ind['rsi14']
    crosses = [i for i in range(1, len(days)) if ma.iloc[i - 1] == ma.iloc[i - 1] and closes.iloc[i - 1] <= ma.iloc[i - 1] and closes.iloc[i] > ma.iloc[i]]
    assert crosses == [60] and round(float(rsi.iloc[60]), 1) == 41.7
    # 逢低加碼：每月 5 日一筆 ＋ 5 日跌 5% 以上加碼（下跌段 0.5%×5 = 2.5% 不夠，崩盤段 2%×5 = 10% 會觸發，最多 10 次、冷卻 5 日）
    extra = [t for t in res['dip']['trades'] if t['rule'] == 1]
    assert sides['dip'] and all(s == 'buy' for s in sides['dip']) and 1 <= len(extra) <= 10
    assert all(t180 <= t['date'] < str(days[227]) for t in extra)                            # 加碼都落在崩盤段（最後一筆的 5 日窗口可跨進盤整段一週）
    # 定投在均線下：只有前一日收盤在 60 日均線下的那些月才買，少於 12 次、多於 0 次
    assert 0 < len(sides['dcama']) < 12 and all(s == 'buy' for s in sides['dcama'])


def test_confirm_buys_when_rsi_already_above_50_at_cross(monkeypatch):
    """盤整 60 日（±0.05% 交錯，RSI 約 50）→ 漲 100 日（每日 +0.5%）→ 崩 40 日（每日 −2%）→ 盤整 30 日：
    上漲第一天穿過 20 日均線時 RSI 已在 50 以上 → 買；崩盤跌破 20 日均線 → 賣光、有賺。"""
    start = date(2021, 1, 4)
    market = _v_market(start, [(60, 'chop'), (100, 0.005), (40, -0.02), (30, 0.0)])
    fm.patch(monkeypatch, market)
    days = sorted(market)
    r = st.simulate_rules(tp.build('confirm', '2330', start, CAPITAL), start, days[-1], CAPITAL)
    fm.check_invariants(r, CAPITAL)
    t = r['trades']
    # 盤整段每隔一天穿線、RSI 剛好過 50 → 來回被洗（買了隔天跌破就賣），每趟小賠：這也是這個策略在盤整裡的性質
    chop = [x for x in t if x['date'] < str(days[60])]
    assert chop and all(abs(x['pnl']) < 1_000 for x in chop if x['side'] == 'sell')
    # 上漲第一天穿線、RSI > 50 → 買一次（沒持股才買，之後一直在均線上）；崩盤跌破 → 賣光、有賺
    rise = [x for x in t if x['side'] == 'buy' and str(days[60]) <= x['date'] < str(days[160])]
    assert len(rise) == 1 and rise[0]['date'] <= str(days[62])
    sell = t[t.index(rise[0]) + 1]
    assert sell['side'] == 'sell' and sell['pnl'] > 0 and str(days[160]) <= sell['date'] < str(days[200])


def test_compare_on_synthetic_is_complete_and_reproducible(no_db):
    src = sm.SyntheticSource(1)
    c = tp.compare('2330', date(2021, 1, 1), date(2022, 12, 31), 500_000, src)
    assert c['available'] and c['n_presets'] == 10 and [x['key'] for x in c['items']] == tp.KEYS
    assert c['source'] == {'kind': 'synthetic', 'seed': 1, 'label': '合成測試資料（種子 1）'} and c['caveat'].startswith(sm.SYNTHETIC_CAVEAT)
    for it in c['items']:
        assert it['trades'] == it['buys'] + it['sells'] and it['missing'] == [] and it['n_rules'] == len(it['texts'])
        assert set(it['metrics']) == set(tp._METRIC_KEYS) and it['metrics']['bench_return'] == c['bench_return']
        assert it['final_value'] == pytest.approx(it['metrics']['final_nav'], abs=0.01)
    by = {x['key']: x for x in c['items']}
    assert by['buyhold']['trades'] == 1 and by['dca']['trades'] == 24 and by['dca']['buys'] == 24
    assert tp.compare('2330', date(2021, 1, 1), date(2022, 12, 31), 500_000, sm.SyntheticSource(1)) == c
    assert tp.compare('2330', date(2022, 1, 1), date(2021, 12, 31), 500_000, src)['available'] is False
    assert tp.compare('2330', date(2009, 1, 1), date(2009, 6, 30), 500_000, src) == {'available': False, 'reason': src.empty_reason, 'errors': None}


def test_api_presets_and_compare(no_db):
    cl = TestClient(api.app)
    r = cl.get('/trading/sim/presets', params={'stock': '2454', 'start': '2022-01-03', 'capital': 200_000})
    assert r.status_code == 200
    body = r.json()
    assert body['stock_id'] == '2454' and [p['key'] for p in body['presets']] == tp.KEYS
    assert body['presets'][0]['rules'][0]['when'] == {'type': 'on_date', 'date': '2022-01-03'} and body['presets'][0]['rules'][0]['then']['qty'] == 100_000
    assert cl.get('/trading/sim/presets', params={'stock': '23'}).status_code == 400
    assert cl.get('/trading/sim/presets', params={'stock': '2330', 'start': 'x'}).status_code == 400
    assert cl.get('/trading/sim/presets', params={'stock': '2330', 'capital': 0}).status_code == 400
    r = cl.post('/trading/sim/presets/compare', json={'stock_id': '2330', 'start': '2022-01-01', 'end': '2022-12-31', 'capital': 300_000, 'source': 'synthetic', 'seed': 2})
    assert r.status_code == 200 and r.json()['n_presets'] == 10 and r.json()['source']['seed'] == 2
    assert cl.post('/trading/sim/presets/compare', json={'stock_id': '2330', 'start': '2022-13-01', 'end': '2022-12-31'}).status_code == 400
    assert cl.post('/trading/sim/presets/compare', json={'stock_id': 'x', 'start': '2022-01-01', 'end': '2022-12-31'}).status_code == 400
    assert cl.post('/trading/sim/presets/compare', json={'stock_id': '2330', 'start': '2022-01-01', 'end': '2022-12-31', 'source': 'fake'}).status_code == 400
    # 不給 source 走真實行情 → 會碰 get_conn（被攔下）：證明預設沒有悄悄變成合成
    with pytest.raises(RuntimeError, match='不得連資料庫'):
        cl.post('/trading/sim/presets/compare', json={'stock_id': '2330', 'start': '2022-01-01', 'end': '2022-12-31'})
