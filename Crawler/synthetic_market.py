"""
交易模擬的資料來源（Iteration 75）：真實行情（資料庫）或合成測試行情（記憶體），兩個模擬器（trading_sim、trading_strategy）
只透過這裡的三個方法拿資料——market_days、load_prices_any、load_bench。

為什麼要合成行情：使用者要在交易模擬頁用「測試資料」操作，不碰資料庫、也不把假資料寫進任何庫（Iteration 74 的方案 A 搬到正式路徑）。
合成行情是每檔獨立的幾何隨機漫步，**同一個 seed、同一個代號，不管期間與同批其他代號是什麼，數字都一樣**
（每檔的亂數種子 = f'{seed}:{stock_id}'，序列固定從 EPOCH 2010-01-01 產生到期末那年年底）。
任何 4～6 碼代號都有行情；0050 也是合成的（當對手）。一字鎖照 trading_rules.is_locked 的定義貼在漲跌停。
"""
import random
from datetime import date, timedelta
from functools import lru_cache

import portfolio_paper as pp
import trading_replay as rp

EPOCH = date(2010, 1, 1)
SOURCES = ('real', 'synthetic')
MAX_SEED = 1_000_000_000
LOCK_PROB = 0.003


def trading_days(start: date, end: date) -> list:
    """週一到週五；不排國定假日（模擬器只看「有行情的日子」，不看日曆）。"""
    d, out = start, []
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


@lru_cache(maxsize=4096)
def _series(stock_id: str, seed: int, end_year: int) -> tuple:
    """(dates, rows)：一檔從 EPOCH 到 end_year 年底的 {open, high, low, close, prev_close}。
    日報酬 N(0.03%, 2%) 夾在 ±10%；開盤在前收附近、高低包住開收；LOCK_PROB 的機率一字鎖在前收 × 1.1 或 × 0.9。"""
    rng = random.Random(f'{seed}:{stock_id}')
    days = trading_days(EPOCH, date(end_year, 12, 31))
    px, prev, rows = rng.uniform(10, 500), None, []
    for _ in days:
        r = max(-0.1, min(0.1, rng.gauss(0.0003, 0.02)))
        c = round(px * (1 + r), 2)
        if prev is not None and rng.random() < LOCK_PROB:
            c = o = h = l = round(px * rng.choice((1.1, 0.9)), 2)
        else:
            o = round(px * (1 + rng.gauss(0, 0.005)), 2)
            h = round(max(o, c) * (1 + abs(rng.gauss(0, 0.005))), 2)
            l = round(min(o, c) * (1 - abs(rng.gauss(0, 0.005))), 2)
        rows.append({'open': o, 'high': h, 'low': l, 'close': c, 'prev_close': prev})
        prev = px = c
    return tuple(days), tuple(rows)


class DbSource:
    """真實行情：就是原本的三個函式。在呼叫時才取模組屬性，tests 用 monkeypatch 換掉它們仍然有效。"""
    kind = 'real'

    def market_days(self, start: date, end: date) -> list:
        return pp.market_days(start, end)

    def load_prices_any(self, ids: list, start: date, end: date) -> dict:
        import trading_sim
        return trading_sim.load_prices_any(ids, start, end)

    def load_bench(self, start: date, end: date) -> dict:
        return rp.load_bench(start, end)

    def describe(self) -> dict:
        return {'kind': 'real', 'label': '真實行情'}

    empty_reason = '這段期間沒有全市場行情（資料從 2018-01 起）'


class SyntheticSource:
    kind = 'synthetic'

    def __init__(self, seed: int = 0, bench: str = pp.BENCH):
        self.seed, self.bench = int(seed), bench

    def market_days(self, start: date, end: date) -> list:
        return trading_days(max(start, EPOCH), end)

    def load_prices_any(self, ids: list, start: date, end: date) -> dict:
        out = {}
        for s in ids:
            days, rows = _series(str(s), self.seed, end.year)
            for d, row in zip(days, rows):
                if start <= d <= end:
                    out.setdefault(d, {})[s] = row
        return out

    def load_bench(self, start: date, end: date) -> dict:
        days, rows = _series(self.bench, self.seed, end.year)
        return {d: row['close'] for d, row in zip(days, rows) if start <= d <= end}

    def describe(self) -> dict:
        return {'kind': 'synthetic', 'seed': self.seed, 'label': f'合成測試資料（種子 {self.seed}）'}

    empty_reason = '合成行情從 2010-01 起，期間要在這之後'


def get_source(name: str = 'real', seed: int = 0):
    """'real' → DbSource；'synthetic' → SyntheticSource(seed)。名字不對丟 ValueError（API 轉 400）。"""
    name = (name or 'real').lower()
    if name not in SOURCES:
        raise ValueError(f"source 要是 {' 或 '.join(SOURCES)}")
    if name == 'real':
        return DbSource()
    if not (0 <= int(seed) <= MAX_SEED):
        raise ValueError(f'seed 要在 0～{MAX_SEED}')
    return SyntheticSource(int(seed))


SYNTHETIC_CAVEAT = '這是合成測試資料（隨機漫步），不是真實行情；數字只用來試功能，沒有任何投資意義。'
