"""Iteration 74 統計（AI/experiments/iter74_fuzz_stats.py）：與 test_trading_fuzz 同一組種子、同一個合成市場，印各趟成交／略過／觸發筆數與耗時（數字給迭代紀錄引用）。不連資料庫。"""
import random
import sys
import time
from datetime import date

sys.path.insert(0, r'E:\Desktop\coding\money\Crawler')
sys.path.insert(0, r'E:\Desktop\coding\money\Crawler\tests')

import portfolio_paper as pp
import trading_replay as rp
import trading_sim as ts
import trading_strategy as st
from helpers import fake_market as fm


class MP:
    def setattr(self, obj, name, value):
        setattr(obj, name, value)


START, END = date(2018, 1, 1), date(2025, 12, 31)
IDS = [fm.BENCH] + [f'{1000 + i}' for i in range(60)]
STOCKS = IDS[1:]
t0 = time.time()
market = fm.make_market(IDS, START, END, seed=7, lock_prob=0.003)
fm.patch(MP(), market)
days = [d for d in sorted(market) if START <= d <= END]
n_lock = sum(1 for d in market for s in market[d] if market[d][s]['high'] == market[d][s]['low'])
print(f'合成市場：{len(IDS)} 檔 × {len(market)} 日（含暖機 450 天；期間內 {len(days)} 日）、一字鎖 {n_lock} 個股票日、產生 {time.time() - t0:.2f}s')
try:
    pp.get_conn()
except RuntimeError as e:
    print('get_conn →', e)

print('| 種子 | 規則 | 成交 | 觸發紀錄（截尾 400） | 總報酬 | 期末持股檔數 | 秒 |')
print('|---|---|---|---|---|---|---|')
for seed in range(5):
    rng = random.Random(seed)
    rules = fm.random_rules(STOCKS, rng, st.MAX_RULES, market)
    t0 = time.time()
    r = st.simulate_rules(rules, START, END)
    fm.check_invariants(r, 1_000_000)
    print(f"| {seed} | {r['n_rules']} | {len(r['trades'])} | {len(r['triggers'])} | {r['metrics']['total_return']:.2%} | {len(r['final']['holdings'])} | {time.time() - t0:.2f} |")

print()
print('| 種子 | 指令 | 成交 | 略過 | 略過原因 | 總報酬 | 秒 |')
print('|---|---|---|---|---|---|---|')
for seed in range(5):
    rng = random.Random(seed)
    text = fm.random_instructions(STOCKS, days, rng, ts.MAX_INSTRUCTIONS, market)
    t0 = time.time()
    r = ts.run_text(text, START, END)
    fm.check_invariants(r, 1_000_000)
    from collections import Counter
    reasons = '、'.join(f'{k} {v}' for k, v in Counter(s['reason'] for s in r['skipped']).most_common())
    print(f"| {seed} | {r['n_instructions']} | {len(r['trades'])} | {len(r['skipped'])} | {reasons} | {r['metrics']['total_return']:.2%} | {time.time() - t0:.2f} |")
