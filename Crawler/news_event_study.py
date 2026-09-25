"""
事件研究法：新聞對追蹤股的異常報酬（Iteration 38 階段 5，方案文件「候選模型 #1」）
────────────────────────────────────────────────────────────────────────
回答一個問題：**新聞到底有沒有訊號**。有，才值得投 LLM 特徵與模型；沒有，先回頭看標籤設計。

做法：
    · 事件 = (股票, effective_date)。同一天多則新聞合併為一個事件，情緒取字典分數均值。
      effective_date 用 news_align 的規則（13:30 前歸當日，否則下一交易日）。
    · 異常報酬 AR_t = 個股日報酬 − 0050 日報酬（市場調整模型；專案沒有加權指數，0050 是最接近的基準）。
    · 視窗 [-5, +5]；報告 AR_0、CAR[0,1]、CAR[0,4]，以及 |AR_0| 對「無新聞日 |AR|」基準。
    · 分組：來源（MOPS 重大訊息 vs 媒體）、字典情緒方向（正／負／中性）、有無個股標記數量。
    · 不依賴 news_schema 的新表，回填一結束就能跑。

輸出：AI/Doc/NewsEventStudy.md（覆蓋）＋主控台。

用法：
    python news_event_study.py [--since 2023-09-01] [--min-abs-sent 0.2]
"""

import argparse
import math
import os
import warnings
from collections import defaultdict
from datetime import date

import numpy as np
import pandas as pd

from db.connection import get_conn

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'AI', 'Doc', 'NewsEventStudy.md')
BENCH = '0050'
WINDOW = 5


def load_prices(stocks: list, since: date) -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql("""
            SELECT stock_id, trade_date, COALESCE(adj_close, close_price) AS px
            FROM stock_daily_prices WHERE stock_id = ANY(%s) AND trade_date >= %s ORDER BY stock_id, trade_date
        """, conn, params=(stocks, since))
    px = df.pivot(index='trade_date', columns='stock_id', values='px').astype(float)
    px = px.where(px > 0)                     # 0 或負值（資料缺漏）→ NaN，否則 log 會出 -inf
    ret = np.log(px).diff()
    return ret.where(ret.abs() < 0.5)         # 單日 |log 報酬| ≥ 0.5 視為壞資料（除權息未還原等）


def load_news(since: date) -> pd.DataFrame:
    with get_conn() as conn:
        return pd.read_sql("""
            SELECT id, platform, title, content, submitted_at, tickers FROM user_news
            WHERE submitted_at >= %s AND tickers IS NOT NULL AND array_length(tickers, 1) > 0
        """, conn, params=(since,))


def tracked() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stock_id FROM stock_info WHERE is_tracking ORDER BY 1")
            return [r[0] for r in cur.fetchall()]


def build_events(news: pd.DataFrame, open_days: list, stocks: set) -> pd.DataFrame:
    from model2_news import _score_text
    import news_align
    rows = []
    for r in news.itertuples(index=False):
        eff, _ = news_align.effective_date(r.submitted_at.to_pydatetime(), open_days, 'TW')
        s = _score_text((r.title or '') + ' ' + (r.content or ''))
        src = 'MOPS' if r.platform == 'MOPS重大訊息' else 'media'
        for tk in set(r.tickers):
            if tk in stocks:
                rows.append({'stock_id': tk, 'eff': eff, 'sent': s, 'src': src})
    ev = pd.DataFrame(rows)
    if ev.empty:
        return ev
    # 同一 (股票, 日) 合併；來源若同時有 MOPS 與媒體，標 both
    g = ev.groupby(['stock_id', 'eff']).agg(n=('sent', 'size'), sent=('sent', 'mean'),
                                            src=('src', lambda x: 'both' if len(set(x)) > 1 else x.iloc[0]))
    return g.reset_index()


def abnormal_returns(ret: pd.DataFrame) -> pd.DataFrame:
    if BENCH not in ret.columns:
        raise RuntimeError(f'缺 {BENCH} 價格，無法做市場調整')
    return ret.sub(ret[BENCH], axis=0).drop(columns=[BENCH])


def window_stats(ar: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    idx = list(ar.index)
    pos = {d: i for i, d in enumerate(idx)}
    recs = []
    for e in events.itertuples(index=False):
        if e.eff not in pos or e.stock_id not in ar.columns:
            continue
        i = pos[e.eff]
        if i - WINDOW < 0 or i + WINDOW >= len(idx):
            continue
        col = ar[e.stock_id].values
        seg = col[i - WINDOW:i + WINDOW + 1]
        if np.isnan(seg).any():
            continue
        recs.append({'stock_id': e.stock_id, 'eff': e.eff, 'n': e.n, 'sent': e.sent, 'src': e.src,
                     'ar0': seg[WINDOW], 'car01': seg[WINDOW:WINDOW + 2].sum(),
                     'car04': seg[WINDOW:].sum(), 'abs_ar0': abs(seg[WINDOW]),
                     'pre_car': seg[:WINDOW].sum()})
    return pd.DataFrame(recs)


def baseline_abs_ar(ar: pd.DataFrame, events: pd.DataFrame) -> float:
    ev_set = set(zip(events.stock_id, events.eff))
    vals = []
    for c in ar.columns:
        s = ar[c].dropna()
        vals += [abs(v) for d, v in s.items() if (c, d) not in ev_set]
    return float(np.mean(vals)) if vals else float('nan')


def tstat(x: pd.Series) -> float:
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else float('nan')


def report(st: pd.DataFrame, base_abs: float, min_abs_sent: float) -> str:
    lines = ['# 新聞事件研究（Iteration 38）', '',
             f'事件 {len(st):,} 個（股票×交易日），視窗 [-{WINDOW}, +{WINDOW}]，'
             f'AR = 個股報酬 − {BENCH} 報酬。無新聞日 |AR| 基準 = **{base_abs * 100:.2f}%**。', '']

    def block(title, df):
        out = [f'## {title}', '', '| 分組 | n | AR₀ | t | CAR[0,1] | CAR[0,4] | \\|AR₀\\| | 相對基準 |',
               '|------|---|-----|---|----------|----------|--------|---------|']
        for name, g in df:
            if len(g) < 5:
                continue
            out.append(f'| {name} | {len(g):,} | {g.ar0.mean() * 100:+.2f}% | {tstat(g.ar0):+.1f} | '
                       f'{g.car01.mean() * 100:+.2f}% | {g.car04.mean() * 100:+.2f}% | '
                       f'{g.abs_ar0.mean() * 100:.2f}% | ×{g.abs_ar0.mean() / base_abs:.2f} |')
        return out + ['']

    st = st.copy()
    st['dir'] = np.where(st.sent >= min_abs_sent, '正面', np.where(st.sent <= -min_abs_sent, '負面', '中性'))
    st['vol'] = pd.cut(st.n, [0, 1, 3, 10, 10 ** 6], labels=['1 則', '2–3 則', '4–10 則', '>10 則'])
    lines += block('全部 vs 來源', [('全部', st)] + list(st.groupby('src')))
    lines += block(f'字典情緒方向（|分數| ≥ {min_abs_sent}）', list(st.groupby('dir')))
    lines += block('當日新聞數', list(st.groupby('vol', observed=True)))
    lines += block('來源 × 方向', list(st.groupby(['src', 'dir'])))
    lines += ['## 判讀', '',
              '- **有訊號**的樣子：負面組 AR₀ 顯著為負、正面組為正（|t| > 2），且 |AR₀| 明顯高於基準（×1.3 以上）。',
              '- |AR₀| 高但方向不分正負：新聞預測**波動**而非方向——與方案文件「主目標建議為波動幅度」一致。',
              '- MOPS 組 |AR₀| 若高於媒體組，官方事件源值得優先做 LLM 抽取。',
              '- 事件前 CAR[-5,-1] 若已與方向同號，代表新聞落後於價格（市場先反應），M2 的 T+0 權重要下修。', '']
    pre = st.groupby('dir').pre_car.mean() * 100
    lines += ['事件前 5 日 CAR（新聞是否落後價格）：' + '、'.join(f'{k} {v:+.2f}%' for k, v in pre.items()), '']
    return '\n'.join(lines)


def main():
    warnings.filterwarnings('ignore')
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', default='2023-09-01')
    ap.add_argument('--min-abs-sent', type=float, default=0.2)
    a = ap.parse_args()
    since = date.fromisoformat(a.since)

    stocks = tracked()
    ret = load_prices(stocks + [BENCH], date(since.year, since.month - 1 if since.month > 1 else 12, 1))
    open_days = list(ret.index)
    news = load_news(since)
    print(f'新聞 {len(news):,} 則（有個股標記）、追蹤股 {len(stocks)} 檔、交易日 {len(open_days)}')
    events = build_events(news, open_days, set(stocks))
    print(f'事件 {len(events):,} 個')
    ar = abnormal_returns(ret)
    st = window_stats(ar, events)
    base = baseline_abs_ar(ar, events)
    md = report(st, base, a.min_abs_sent)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(md)
    print(md)
    print(f'\n→ {os.path.abspath(OUT)}')


if __name__ == '__main__':
    main()
