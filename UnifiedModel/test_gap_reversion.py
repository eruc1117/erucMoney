"""
跳空回吐效應（Iteration 15）
────────────────────────────
`verify_us_correlation.py` 發現：

    美股隔夜 → 台股開盤跳空   相關 +0.66（極強）
    美股隔夜 → 台股盤中報酬   相關 −0.13（微負）
    美股隔夜 → 台股全日報酬   相關 +0.35

也就是說美股資訊在**開盤瞬間就被完全吸收**，這正是它加進「收盤到收盤」
預測模型沒有幫助的原因——不是沒有關連，而是關連已被價格反映。

但那個 −0.13 的盤中負相關值得追究：它暗示**跳空後會部分回吐**。
本腳本量化這個效應是否足以構成可交易的策略：

  依美股隔夜漲跌幅分組，看台股當日「開盤到收盤」的報酬
  若跳空愈大、盤中回吐愈明顯，即為可利用的模式（需盤中執行）

同時報告樣本數與標準誤——微弱效應在大樣本上容易顯著但幅度不足以覆蓋交易成本。

用法：python test_gap_reversion.py
產出：results/gap_reversion.md
"""

import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'Crawler'))

from us_features import build_us_daily, LOAD_US_SQL   # noqa: E402
from verify_us_correlation import load_tw_market      # noqa: E402

RESULTS_DIR = os.path.join(BASE_DIR, 'results')
SIGNAL = 'us_soxx_ret1'      # 相關性最強者


def main():
    from db.connection import get_conn
    print('載入資料…')
    mkt = load_tw_market()
    with get_conn() as conn:
        raw_us = pd.read_sql(LOAD_US_SQL, conn)
    us = build_us_daily(raw_us)

    df = pd.merge_asof(
        mkt.sort_values('trade_date'),
        us[['us_date', SIGNAL]].sort_values('us_date'),
        left_on='trade_date', right_on='us_date',
        direction='backward', allow_exact_matches=False,
    ).dropna(subset=[SIGNAL, 'gap', 'intraday'])

    print(f'樣本 {len(df)} 個交易日'
          f'（{str(df["trade_date"].min())[:10]} ~ {str(df["trade_date"].max())[:10]}）\n')

    # 依美股隔夜漲跌幅分成五組
    df['bucket'] = pd.qcut(df[SIGNAL], 5,
                           labels=['最跌 20%', '偏跌', '持平', '偏漲', '最漲 20%'])

    rows = []
    for b, g in df.groupby('bucket', observed=True):
        n = len(g)
        intr = g['intraday']
        se = intr.std() / np.sqrt(n)
        rows.append({
            'bucket': str(b),
            'n': n,
            'us_ret': g[SIGNAL].mean(),
            'gap': g['gap'].mean(),
            'intraday': intr.mean(),
            'intraday_se': se,
            't': intr.mean() / se if se > 0 else 0.0,
            'win_rate': float((intr > 0).mean()),
        })

    print(f"{'美股隔夜分組':12} {'n':>5} {'美股平均':>9} {'台股跳空':>9} "
          f"{'盤中報酬':>9} {'標準誤':>8} {'t值':>7} {'盤中上漲率':>9}")
    print('-' * 82)
    for r in rows:
        print(f"{r['bucket']:12} {r['n']:5} {r['us_ret']:+8.2%} {r['gap']:+8.2%} "
              f"{r['intraday']:+8.3%} {r['intraday_se']:7.3%} {r['t']:+7.2f} "
              f"{r['win_rate']:8.1%}")

    # 極端組的價差＝跳空回吐策略的毛報酬
    lo, hi = rows[0], rows[-1]
    spread = lo['intraday'] - hi['intraday']
    spread_se = np.sqrt(lo['intraday_se'] ** 2 + hi['intraday_se'] ** 2)
    print(f"\n最跌組 − 最漲組 的盤中報酬價差 = {spread:+.3%} "
          f"± {spread_se:.3%}（t = {spread / spread_se:+.2f}）")
    print('（意義：美股大跌後做多台股、美股大漲後做空，當日盤中的毛報酬）')

    write_report(rows, spread, spread_se, len(df))


def write_report(rows, spread, spread_se, n):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'gap_reversion.md')
    lines = [
        '# 跳空回吐效應量化（Iteration 15）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**樣本：** {n} 個交易日　**訊號：** 費半 ETF（SOXX）隔夜漲跌',
        '',
        '> 背景：美股隔夜與台股**開盤跳空**相關 +0.66，但與**盤中報酬**相關 −0.13。',
        '> 本表檢驗這個負相關是否構成可交易的回吐效應。',
        '',
        '| 美股隔夜分組 | 樣本數 | 美股平均 | 台股跳空 | 台股盤中報酬 | 標準誤 | t 值 | 盤中上漲率 |',
        '|-------------|-------|---------|---------|-------------|-------|------|-----------|',
    ]
    for r in rows:
        lines.append(f"| {r['bucket']} | {r['n']} | {r['us_ret']:+.2%} | "
                     f"{r['gap']:+.2%} | **{r['intraday']:+.3%}** | "
                     f"{r['intraday_se']:.3%} | {r['t']:+.2f} | {r['win_rate']:.1%} |")
    lines += [
        '',
        f'**最跌組 − 最漲組的盤中報酬價差：{spread:+.3%} ± {spread_se:.3%}'
        f'（t = {spread / spread_se:+.2f}）**',
        '',
        '## 解讀',
        '',
        '- 台股開盤跳空**確實**跟隨美股（跳空欄由負到正單調變化）。',
        '- 盤中報酬呈相反方向即為回吐：美股大漲 → 台股高開 → 當日盤中偏跌。',
        '- **但要能利用它必須在開盤價成交**。本專案的資料與模型都是日線收盤，',
        '  無法驗證開盤成交的滑價與流動性，故僅記錄現象，不作為策略部署。',
        '- 幅度須與交易成本比較：台股單邊手續費約 0.1425%（常有折扣）、',
        '  賣出證交稅 0.3%，來回成本約 0.4~0.6%。**毛報酬若低於此即無實質意義。**',
    ]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'\n報告已寫入 {path}')


if __name__ == '__main__':
    main()
