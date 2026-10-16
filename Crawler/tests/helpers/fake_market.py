"""
合成行情（Iteration 74）：給交易模擬（trading_sim、trading_strategy）大量假資料做測試，**完全在記憶體**，不連任何資料庫。

為什麼不灌測試庫：兩個模擬器只透過三個函式碰資料——portfolio_paper.market_days、trading_replay.load_prices、trading_replay.load_bench——
其餘是純計算；把這三個換掉就能跑 8 年 × 幾十檔的假行情，而 market_days 要每天 ≥ 500 列才算交易日，灌庫 8 年要 100 萬列、20 秒以上。
patch() 另外把 get_conn 換成直接丟例外：任何沒攔到的資料庫存取會當場失敗，而不是碰到任何庫（含測試庫）。

用法（pytest）：
    market = fake_market.make_market(['0050', '1111', '2222'], date(2020, 1, 1), date(2023, 12, 31), seed=1)
    fake_market.patch(monkeypatch, market)
    r = trading_strategy.simulate_rules(rules, date(2020, 1, 1), date(2023, 12, 31))
    fake_market.check_invariants(r, capital=1_000_000)
"""
import random
from datetime import date, timedelta

import portfolio_paper as pp
import trading_replay as rp
import trading_strategy as st

BENCH = '0050'
NO_DB_MSG = 'fake_market：這個測試不得連資料庫（get_conn 已被攔下）'


def trading_days(start: date, end: date) -> list:
    """週一到週五；不排國定假日（模擬器只看「有行情的日子」，不看日曆）。"""
    d, out = start, []
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def make_market(ids: list, start: date, end: date, seed: int = 0, lock_prob: float = 0.0, warmup_days: int = 450,
                vol: float = 0.02, drift: float = 0.0003, lock_ids: tuple = ()) -> dict:
    """{trade_date: {sid: {open, high, low, close, prev_close}}}，從 start − warmup_days 起（規則模擬的指標要 420 天暖機）。
    每檔幾何隨機漫步：日報酬 ~ N(drift, vol) 夾在 ±10%（漲跌停）；開盤在前收附近，高低包住開收。
    lock_prob：任一天一字鎖（開高低收同價、貼漲停或跌停，fill_orders 視為不成交）的機率；lock_ids 裡的股票除第一天外天天鎖。同一 seed 結果相同。"""
    rng = random.Random(seed)
    days = trading_days(date.fromordinal(start.toordinal() - warmup_days), end)
    out = {d: {} for d in days}
    for s in ids:
        px, prev = rng.uniform(10, 500), None
        for d in days:
            r = max(-0.1, min(0.1, rng.gauss(drift, vol)))
            c = round(px * (1 + r), 2)
            if prev is not None and (s in lock_ids or rng.random() < lock_prob):
                c = o = h = l = round(px * rng.choice((1.1, 0.9)), 2)       # fill_orders 的一字鎖＝高低同價且離前收 ≥ LIMIT_LOCK，所以要貼在漲跌停
            else:
                o = round(px * (1 + rng.gauss(0, 0.005)), 2)
                h = round(max(o, c) * (1 + abs(rng.gauss(0, 0.005))), 2)
                l = round(min(o, c) * (1 - abs(rng.gauss(0, 0.005))), 2)
            out[d][s] = {'open': o, 'high': h, 'low': l, 'close': c, 'prev_close': prev}
            prev = px = c
    return out


def _no_db(*_a, **_k):
    raise RuntimeError(NO_DB_MSG)


def patch(monkeypatch, market: dict, bench_sid: str = BENCH) -> None:
    """換掉三個資料函式，並把 get_conn 全部攔下。
    路由照正式庫：bench_sid 只在 table='stock_daily_prices' 找得到、其他股票只在 market_daily_prices——這樣 load_prices_any 的回退路徑也會被走到。"""
    days = sorted(market)

    def market_days(start, end):
        return [d for d in days if start <= d <= end]

    def load_prices(ids, start, end, table='market_daily_prices'):
        assert table in ('market_daily_prices', 'stock_daily_prices')
        want = [s for s in ids if (s == bench_sid) == (table == 'stock_daily_prices')]
        out = {}
        for d in days:
            if d < start or d > end:
                continue
            row = {s: market[d][s] for s in want if s in market[d]}
            if row:
                out[d] = row
        return out

    def load_bench(start, end):
        return {d: market[d][bench_sid]['close'] for d in days if start <= d <= end and bench_sid in market[d]}

    monkeypatch.setattr(pp, 'market_days', market_days)
    monkeypatch.setattr(rp, 'load_prices', load_prices)
    monkeypatch.setattr(rp, 'load_bench', load_bench)
    import db.connection as dbc
    for mod in (dbc, pp, rp):
        monkeypatch.setattr(mod, 'get_conn', _no_db)


# ── 隨機規則與指令 ───────────────────────────────────────────────────────────

def _qty(rng: random.Random, capital: float, ref_price: float) -> tuple:
    """買進數量按資金縮放（約 1%～30% 的資金，用這檔在市場裡的第一個收盤當參考價），
    否則多數指令會因「現金不夠」被略過、或一筆就把資金買光，測不到幾筆成交。"""
    unit = rng.choice(['股', '張', '元'])
    budget = capital * rng.uniform(0.01, 0.3)
    if unit == '元':
        return int(budget), unit
    if unit == '張':
        return max(1, int(budget / ref_price / 1000)), unit
    return max(1, int(budget / ref_price)), unit


def _ref_prices(market: dict, ids: list) -> dict:
    first = {}
    for d in sorted(market):
        for s in ids:
            if s not in first and s in market[d]:
                first[s] = market[d][s]['close']
    return first


def random_rules(ids: list, rng: random.Random, n: int, market: dict, capital: float = 1_000_000) -> list:
    """n 條合法規則：14 種條件均勻抽（不保證每種都出現），三成包成 and／or 群組；買賣各半、賣用「全部」或股數。"""
    ref = _ref_prices(market, ids)
    rules = []
    for _ in range(n):
        s = rng.choice(ids)
        kind = rng.choice(list(st.CONDITIONS))
        w = {'type': kind}
        params = st.CONDITIONS[kind][0]
        if 'n' in params:
            w['n'] = rng.choice([2, 5, 10, 20, 60, 120, 250])
        if 'x' in params:
            w['x'] = rng.choice([5, 10, 20, 30, 50, 70, 100, 300])
        if 'd' in params:
            w['d'] = rng.randint(1, 28)
        if 'date' in params:
            w['date'] = str(date(2018, 1, 1) + timedelta(days=rng.randint(0, 3200)))
        if rng.random() < 0.3:
            other = {'type': rng.choice(['below_ma', 'above_ma']), 'n': rng.choice([5, 20, 60])}
            w = {'op': rng.choice(['and', 'or']), 'conds': [w, other]}
        if rng.random() < 0.5:
            q, unit = _qty(rng, capital, ref[s])
            then = {'side': 'buy', 'qty': q, 'unit': unit}
        else:
            then = rng.choice([{'side': 'sell', 'unit': '全部'}, {'side': 'sell', 'qty': rng.randint(1, 3000), 'unit': '股'}])
        rules.append({'stock_id': s, 'when': w, 'then': then, 'max_times': rng.choice([None, 1, 3, 10]), 'cooldown': rng.choice([0, 0, 5, 20])})
    return rules


def random_instructions(ids: list, days: list, rng: random.Random, n: int, market: dict, capital: float = 1_000_000) -> str:
    """n 行指令文字（含週末日期，測順延）；六成買、四成賣。"""
    ref = _ref_prices(market, ids)
    lines = []
    for _ in range(n):
        d = rng.choice(days) + timedelta(days=rng.choice([0, 0, 0, 1, 2]))
        s = rng.choice(ids)
        if rng.random() < 0.6:
            q, unit = _qty(rng, capital, ref[s])
            lines.append(f'{d} 買 {s} {q}{unit}')
        else:
            lines.append(f'{d} 賣 {s} ' + rng.choice(['全部', f'{rng.randint(1, 3000)}股']))
    return '\n'.join(lines)


# ── 不變量 ───────────────────────────────────────────────────────────────────

def check_invariants(r: dict, capital: float) -> None:
    """兩個模擬器共用的結果結構：現金不為負、持股為正、成交價量為正、淨值為正，
    而且**帳要對**：期末現金 = 資金 − Σ買(成交額＋手續費) ＋ Σ賣(成交額 − 手續費 − 稅)；每檔期末股數 = Σ買股 − Σ賣股。"""
    assert r['available'], r.get('reason')
    assert r['final']['cash'] >= -1e-6, r['final']['cash']
    cash, shares = float(capital), {}
    for t in r['trades']:
        assert t['shares'] > 0 and t['price'] > 0 and t['fee'] >= 0 and t['tax'] >= 0, t
        assert t['gross'] == round(t['shares'] * t['price'], 2), t
        if t['side'] == 'buy':
            cash -= t['gross'] + t['fee']
            shares[t['stock_id']] = shares.get(t['stock_id'], 0) + t['shares']
        else:
            cash += t['gross'] - t['fee'] - t['tax']
            shares[t['stock_id']] = shares.get(t['stock_id'], 0) - t['shares']
            assert shares[t['stock_id']] >= 0, ('賣超過持股', t)
    assert abs(cash - r['final']['cash']) <= 0.01 * (len(r['trades']) + 1), (cash, r['final']['cash'])
    held = {h['stock_id']: h['shares'] for h in r['final']['holdings']}
    assert all(n > 0 for n in held.values()), held
    assert held == {s: n for s, n in shares.items() if n > 0}, (held, shares)
    assert abs(r['final']['value'] - r['final']['cash'] - sum(h['value'] for h in r['final']['holdings'])) < 0.01
    dates = [p['d'] for p in r['series']]
    assert dates == sorted(dates) and all(p['nav'] > 0 and p['bench'] > 0 for p in r['series'])
    if r['metrics']:
        assert abs(r['metrics']['final_nav'] - r['final']['value']) < 0.01
