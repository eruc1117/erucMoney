"""Iteration 79：十種策略範本套在真實行情（唯讀）與合成行情上各跑一次，寫結果檔 UnifiedModel/results/trading_presets_iter79.md。
執行：cd Crawler && PYTHONUTF8=1 python ../AI/experiments/iter79_presets.py（經 record_check.js --name presets-run-79）
真實行情：2018-01-02～2024-09-30（保留期 2024-10 起不碰），四檔；合成：種子 0、同期間、2330（對照——隨機漫步上的數字沒有意義）。
這不是月調倉回測，不寫 portfolio_runs。"""
import os
import sys
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'Crawler'))

import synthetic_market as sm       # noqa: E402
import trading_presets as tp        # noqa: E402

START, END, CAPITAL = date(2018, 1, 2), date(2024, 9, 30), 1_000_000
STOCKS = ['2330', '2317', '2454', '2603']
OUT = os.path.join(HERE, '..', '..', 'UnifiedModel', 'results', 'trading_presets_iter79.md')


def pct(v):
    return '–' if v is None else f'{v * 100:+.1f}%'


def table(c):
    lines = ['| 策略 | 成交（買／賣） | 總報酬 | 主動（對 0050） | 年化主動 | 最大回撤 | 月勝率 | 期末現金占比 |', '|---|---|---|---|---|---|---|---|']
    for it in sorted(c['items'], key=lambda x: -(x['metrics']['total_return'] or 0)):
        m = it['metrics']
        win = '–' if m['monthly_win_rate'] is None else f"{m['monthly_win_rate'] * 100:.0f}%"
        lines.append(f"| {it['label']}（`{it['key']}`） | {it['trades']}（{it['buys']}／{it['sells']}） | {pct(m['total_return'])} | {pct(m['active_return'])} | {pct(m['ann_active'])} | "
                     f"{pct(m['mdd_port'])} | {win} | {it['final_cash'] / it['final_value'] * 100:.0f}% |")
    return '\n'.join(lines)


def main():
    out = [f'# 十種策略範本的比較（Iteration 79，{date.today()}）', '',
           f'期間 {START}～{END}、資金 {CAPITAL:,}、每檔單獨跑；0050 含息是對手。策略定義在 `Crawler/trading_presets.py`，模擬器是 `trading_strategy.simulate_rules`'
           '（收盤判斷、隔天開盤市價、手續費 0.0855%、賣出稅 0.3%）。', '',
           tp.CAVEAT, '']
    for sid in STOCKS:
        t0 = time.time()
        c = tp.compare(sid, START, END, CAPITAL, sm.DbSource())
        dt = time.time() - t0
        out.append(f'## {sid}（真實行情，{dt:.1f} 秒）')
        if not c['available']:
            out += ['', f"沒辦法跑：{c['reason']}", '']
            continue
        out += ['', f"0050 含息同期 {pct(c['bench_return'])}；缺行情的範本：{sum(1 for x in c['items'] if x['missing'])}", '', table(c), '']
        print(sid, f'{dt:.1f}s', 'bench', pct(c['bench_return']), 'best', max(c['items'], key=lambda x: x['metrics']['total_return'] or 0)['key'])
    t0 = time.time()
    c = tp.compare('2330', START, END, CAPITAL, sm.SyntheticSource(0))
    out += [f'## 2330（合成行情、種子 0，{time.time() - t0:.1f} 秒）——對照組，數字沒有意義', '', c['caveat'], '',
            f"0050 合成序列同期 {pct(c['bench_return'])}", '', table(c), '']
    print('synthetic bench', pct(c['bench_return']))
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    print('wrote', os.path.relpath(OUT, os.path.join(HERE, '..', '..')))


if __name__ == '__main__':
    main()
