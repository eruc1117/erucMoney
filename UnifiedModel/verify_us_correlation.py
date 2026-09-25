"""
美股與台股的相關性直接量測（Iteration 15）
──────────────────────────────────────────
Iteration 14 的結論是「美股特徵無助於預測」，但那測的是**增量預測力**，
從未直接量測**原始相關性**。兩者是不同的問題，必須分開回答：

  問題 A 美股隔夜與台股次日到底相不相關？（原始相關係數）
  問題 B 若相關，為何加進模型沒有幫助？

關鍵假設（本腳本要驗證的）：
  台股**開盤價**會直接跳空反映美股隔夜走勢。
  若是如此，美股資訊在你能交易之前就已經被開盤價吸收，
  對「收盤到收盤」的報酬自然沒有預測力——
  相關性存在，但沒有可交易的 edge。

因此把台股次日報酬拆成三段分別檢驗：
  開盤跳空  open / 前一日 close − 1     ← 美股資訊應該集中在這裡
  盤中報酬  close / open − 1            ← 開盤後才發生，美股資訊應已耗盡
  全日報酬  close / 前一日 close − 1    ← 前兩者相加，也是模型原本的預測目標

另外驗證時序對齊是否正確（用「未來的美股資料」當對照，
若對齊有誤，正確版與洩漏版的相關係數會非常接近）。

用法：python verify_us_correlation.py
產出：results/us_correlation_check.md
"""

import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'Crawler'))

from us_features import build_us_daily, LOAD_US_SQL   # noqa: E402

RESULTS_DIR = os.path.join(BASE_DIR, 'results')

TW_SQL = """
    SELECT stock_id, trade_date, open_price AS open, close_price AS close
    FROM stock_daily_prices
    WHERE close_price > 0 AND open_price > 0
    ORDER BY stock_id, trade_date
"""


def load_tw_market() -> pd.DataFrame:
    """台股大盤（等權平均）的開盤跳空／盤中／全日報酬。"""
    from db.connection import get_conn
    with get_conn() as conn:
        df = pd.read_sql(TW_SQL, conn)

    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.sort_values(['stock_id', 'trade_date'])
    g = df.groupby('stock_id')
    prev_close = g['close'].shift(1)

    df['gap']      = df['open'] / prev_close - 1        # 開盤跳空
    df['intraday'] = df['close'] / df['open'] - 1       # 盤中
    df['full']     = df['close'] / prev_close - 1       # 全日

    mkt = (df.groupby('trade_date')[['gap', 'intraday', 'full']]
           .mean().reset_index())
    counts = df.groupby('trade_date')['stock_id'].nunique()
    mkt = mkt[mkt['trade_date'].map(counts) >= 5].dropna().reset_index(drop=True)
    return mkt


def align(mkt: pd.DataFrame, us: pd.DataFrame, leak: bool) -> pd.DataFrame:
    """
    leak=False：美股日期 < 台股日期（正確；只用開盤前已知的資訊）
    leak=True ：允許同日（洩漏；用到台股收盤後才公布的美股收盤）
    對照兩者可驗證對齊邏輯是否真的生效。
    """
    merged = pd.merge_asof(
        mkt.sort_values('trade_date'), us.sort_values('us_date'),
        left_on='trade_date', right_on='us_date',
        direction='backward', allow_exact_matches=leak,
    )
    return merged


def corr_table(df: pd.DataFrame, us_cols: list) -> pd.DataFrame:
    rows = []
    for c in us_cols:
        if c not in df.columns:
            continue
        sub = df[[c, 'gap', 'intraday', 'full']].dropna()
        if len(sub) < 100:
            continue
        rows.append({
            '美股特徵': c,
            'n': len(sub),
            '開盤跳空': sub[c].corr(sub['gap']),
            '盤中報酬': sub[c].corr(sub['intraday']),
            '全日報酬': sub[c].corr(sub['full']),
        })
    return pd.DataFrame(rows)


def main():
    from db.connection import get_conn
    print('載入資料…')
    mkt = load_tw_market()
    with get_conn() as conn:
        raw_us = pd.read_sql(LOAD_US_SQL, conn)
    us = build_us_daily(raw_us)
    print(f'台股大盤 {len(mkt)} 個交易日'
          f'（{str(mkt["trade_date"].min())[:10]} ~ {str(mkt["trade_date"].max())[:10]}）')

    key_cols = ['us_spy_ret1', 'us_qqq_ret1', 'us_soxx_ret1',
                'us_nvda_ret1', 'us_tsm_ret1', 'us_umc_ret1', 'us_semi_breadth']

    ok = corr_table(align(mkt, us, leak=False), key_cols)
    print('\n=== 正確對齊（美股日期 < 台股日期）===')
    print(ok.to_string(index=False, float_format=lambda v: f'{v:+.4f}'))

    leaked = corr_table(align(mkt, us, leak=True), key_cols)
    print('\n=== 洩漏對照（允許同日，僅供驗證對齊邏輯）===')
    print(leaked.to_string(index=False, float_format=lambda v: f'{v:+.4f}'))

    # 個股層級：TSM ADR 對 2330、UMC ADR 對 2303
    print('\n=== 個股 ADR 對照 ===')
    pair_rows = []
    with get_conn() as conn:
        tw = pd.read_sql(TW_SQL, conn)
    tw['trade_date'] = pd.to_datetime(tw['trade_date'])
    for sid, adr in (('2330', 'us_tsm_ret1'), ('2303', 'us_umc_ret1')):
        s = tw[tw['stock_id'] == sid].sort_values('trade_date').copy()
        pc = s['close'].shift(1)
        s['gap'] = s['open'] / pc - 1
        s['intraday'] = s['close'] / s['open'] - 1
        s['full'] = s['close'] / pc - 1
        m = pd.merge_asof(s[['trade_date', 'gap', 'intraday', 'full']].dropna(),
                          us[['us_date', adr]].sort_values('us_date'),
                          left_on='trade_date', right_on='us_date',
                          direction='backward', allow_exact_matches=False).dropna()
        if len(m) < 100:
            continue
        pair_rows.append({'台股': sid, '美股 ADR': adr, 'n': len(m),
                          '開盤跳空': m[adr].corr(m['gap']),
                          '盤中報酬': m[adr].corr(m['intraday']),
                          '全日報酬': m[adr].corr(m['full'])})
    pairs = pd.DataFrame(pair_rows)
    print(pairs.to_string(index=False, float_format=lambda v: f'{v:+.4f}'))

    write_report(ok, leaked, pairs, len(mkt))


def write_report(ok, leaked, pairs, n_days):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'us_correlation_check.md')

    def tbl(df, cols):
        head = '| ' + ' | '.join(cols) + ' |'
        sep = '|' + '|'.join(['---'] * len(cols)) + '|'
        lines = [head, sep]
        for _, r in df.iterrows():
            cells = []
            for c in cols:
                v = r[c]
                cells.append(f'{v:+.4f}' if isinstance(v, float) else str(v))
            lines.append('| ' + ' | '.join(cells) + ' |')
        return lines

    lines = [
        '# 美股與台股相關性直接量測（Iteration 15）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**台股大盤序列：** {n_days} 個交易日（24 檔等權平均）',
        '',
        '> Iteration 14 測的是「美股特徵能否**提升預測**」，本次直接量測**原始相關性**。',
        '> 台股次日報酬拆成三段：開盤跳空 / 盤中 / 全日。',
        '',
        '## 正確對齊（美股日期 < 台股日期）',
        '',
    ]
    lines += tbl(ok, ['美股特徵', 'n', '開盤跳空', '盤中報酬', '全日報酬'])
    lines += ['', '## 洩漏對照（允許同日，僅用於驗證對齊邏輯確實生效）', '']
    lines += tbl(leaked, ['美股特徵', 'n', '開盤跳空', '盤中報酬', '全日報酬'])
    if len(pairs):
        lines += ['', '## 個股 ADR 對照', '']
        lines += tbl(pairs, ['台股', '美股 ADR', 'n', '開盤跳空', '盤中報酬', '全日報酬'])
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'\n報告已寫入 {path}')


if __name__ == '__main__':
    main()
