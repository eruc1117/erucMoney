"""
MOPS 重大訊息分類與事件研究（Iteration 39，新聞訊號研究方案階段 3）
────────────────────────────────────────────────────────────────
方案排序：月營收 → 財報 → MOPS 重大訊息 → 媒體。MOPS 公告有法定精確時間戳、內生性低，
但事件類型異質，方案要求「需先分類」。Iteration 38 只把 MOPS 當一整組（MOPS-only 日 AR₀ −0.35%，t −5.4），
分不出是哪一類在動。

分類：主旨用規則（正則）分 20 類，先比對明確類別，最後才落到「董事會決議」與「其他」。
不用 LLM——6,137 則公告主旨是高度樣板化的法定用語，規則比對的可靠度高於抽樣 60 則的 LLM 一致率，
而且每次重跑結果相同。分類結果寫 `news_llm_feature`（model = 'rule_mops_v1'），欄位對齊 LLM 抽取的格式，
之後 M2 可以直接當特徵。

事件研究：事件 = (股票, effective_date, 類別)，13:30 規則；AR = 個股 − 其他追蹤股等權均值（預設；0050 由台積電主導，
用它當基準會讓每檔都帶共同負漂移，--bench 0050 可對照）；報告每類的 AR₀、|AR₀| ÷ 自身基準、CAR[1,5]、CAR[1,20]
（CAR 只用「不重疊」子集：同股同類事件間隔 ≥ 21 個交易日，否則台積電子公司每週買債券的 t 值會虛高），
並分「當天有沒有媒體新聞」——公告當天沒有媒體跟進的，才是市場只從 MOPS 得知的事件。

用法：
    python mops_event_study.py [--since 2023-09-01] [--no-persist] [--bench ew|0050]
"""

import argparse
import math
import os
import re
import warnings
from datetime import date, datetime, time as dtime, timedelta

import numpy as np
import pandas as pd

from db.connection import get_conn

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'AI', 'Doc', 'MopsEventStudy.md')
BENCH = '0050'
MODEL = 'rule_mops_v1'
PRE, POST = 10, 20
CLOSE_TW = dtime(13, 30)

# (類別, 是否例行, 正則) —— 依序比對，先明確後籠統
RULES = [
    ('營收', True, r'營收|自結.*盈餘|營業收入'),
    ('財報-季報', True, r'(第[一二三四1-4]季|年度|Q[1-4]|上半年).*(財務報告|財報|財務報表)|(財務報告|財報|財務報表).*(第[一二三四1-4]季|年度)'),
    ('財報-自結', True, r'財務報告|財報|財務報表'),
    ('股利', True, r'股利|配息|除息|除權|盈餘分配'),
    ('法說會', True, r'法人說明會|法說會|說明會|受邀|論壇|研討會|Forum|Conference|Summit|投資人會議'),
    ('股東會', True, r'股東常會|股東臨時會|股東會|競業禁止'),
    ('庫藏股', False, r'買回股份|庫藏股'),
    ('員工股權', True, r'限制員工權利新股|員工認股權|員工持股|認股權憑證'),
    ('澄清媒體', False, r'媒體報導|澄清|說明.*報導|傳聞'),
    ('注意交易', False, r'注意交易|公布注意|異常交易|處置'),
    ('訴訟裁罰', False, r'訴訟|裁罰|罰鍰|仲裁|判決|處分書|檢調|搜索|調查'),
    ('捐贈', True, r'捐贈|捐助|公益'),
    ('人事異動', False, r'董事長|總經理|發言人|財務主管|會計主管|內部稽核|研發主管|獨立董事|董事.*(辭任|異動|變動|補選|當選|解任)|'
                       r'經理人|人事|辭任|新任|委任|解任'),
    ('併購投資', False, r'合併|收購|併購|投資設立|轉投資|股權|出售|讓與|設立.*公司|策略聯盟|合資|參與.*增資|投資'),
    ('減資增資', False, r'減資|現金增資|發行新股|私募|增資'),
    ('可轉債', True, r'轉換公司債|公司債|債券'),
    ('背書保證', True, r'背書保證|資金貸與|保證'),
    ('有價證券交易', True, r'取得有價證券|處分有價證券|有價證券|固定收益|理財商品|基金|定存|受益憑證|取得.*證券|處分.*證券'),
    ('資本支出', True, r'機器設備|廠務|不動產|資本預算|資本支出|資本化租賃|訂購|購置|廠房|設備'),
    ('更正', True, r'更正|補充|勘誤'),
    ('董事會決議', True, r'董事會'),
]
EXPECTED = {c: e for c, e, _ in RULES}
EXPECTED['其他'] = False
_COMPILED = [(c, re.compile(p)) for c, _, p in RULES]


def classify(subject: str) -> str:
    s = re.sub(r'^.*?（\d{4,6}）', '', subject or '')       # 去掉「公司名（代號）」前綴
    s = re.sub(r'^\s*(代子公司|本公司代子公司)[^公]*公司', '子公司', s)
    for cat, rx in _COMPILED:
        if rx.search(s):
            return cat
    return '其他'


# ── 資料 ──────────────────────────────────────────────────────────────────────
def load_mops(since: date) -> pd.DataFrame:
    with get_conn() as conn:
        return pd.read_sql("""
            SELECT id, title, submitted_at, tickers FROM user_news
            WHERE platform = 'MOPS重大訊息' AND submitted_at >= %s AND tickers IS NOT NULL AND array_length(tickers, 1) > 0
            ORDER BY submitted_at""", conn, params=(since,))


def load_media_days(since: date) -> set:
    """(ticker, effective_date) 有媒體新聞的集合（非 MOPS），用 news_price_link；表不存在則空集合。"""
    with get_conn() as conn:
        try:
            df = pd.read_sql("""
                SELECT DISTINCT l.ticker, l.effective_date FROM news_price_link l
                JOIN user_news n ON n.id = l.news_id
                WHERE l.market = 'TW' AND n.platform <> 'MOPS重大訊息' AND l.effective_date >= %s""", conn, params=(since,))
        except Exception:      # noqa: BLE001
            return set()
    return set(zip(df.ticker, pd.to_datetime(df.effective_date).dt.date))


def load_returns(stocks: list, since: date) -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql("""
            SELECT stock_id, trade_date, COALESCE(adj_close, close_price) AS px FROM stock_daily_prices
            WHERE stock_id = ANY(%s) AND trade_date >= %s ORDER BY 1, 2""", conn, params=(stocks, since))
    px = df.pivot(index='trade_date', columns='stock_id', values='px').astype(float)
    px = px.where(px > 0)
    ret = np.log(px).diff()
    return ret.where(ret.abs() < 0.5)


def persist(df: pd.DataFrame) -> int:
    from psycopg2.extras import execute_values
    rows = [(int(r.id), MODEL, r.cat, 'neutral', 1, bool(EXPECTED[r.cat]), list(r.tickers), [], 'TW', 0.6,
             'regex on MOPS subject') for r in df.itertuples(index=False)]
    if not rows:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO news_llm_feature (news_id, model, event_type, direction, magnitude, is_expected,
                    affected_tickers, affected_sectors, scope, confidence, rationale)
                VALUES %s ON CONFLICT (news_id, model) DO UPDATE SET
                    event_type = EXCLUDED.event_type, is_expected = EXCLUDED.is_expected,
                    affected_tickers = EXCLUDED.affected_tickers, extracted_at = NOW()""", rows, page_size=500)
        conn.commit()
    return len(rows)


# ── 事件研究 ──────────────────────────────────────────────────────────────────
def tstat(x) -> float:
    x = pd.Series(x).dropna()
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else float('nan')


def build(since: date, bench: str = 'ew') -> dict:
    import news_align
    mops = load_mops(since)
    mops['cat'] = mops.title.map(classify)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stock_id FROM stock_info WHERE is_tracking ORDER BY 1")
            stocks = [r[0] for r in cur.fetchall()]
    ret = load_returns(stocks + [BENCH], since - timedelta(days=120))
    if bench == 'ew':
        # 等權基準：其他追蹤股當日均值（排除自己）。0050 由台積電主導，2023~2026 大漲，
        # 用它當基準會讓每一檔都帶共同的負漂移，事件研究的 CAR 全部往下偏。
        cols = [c for c in ret.columns if c != BENCH and c not in ('0052', '0056')]
        tot, cnt = ret[cols].sum(axis=1), ret[cols].notna().sum(axis=1)
        ar = pd.DataFrame({c: ret[c] - (tot - ret[c].fillna(0)) / (cnt - ret[c].notna().astype(int)).replace(0, np.nan)
                           for c in cols})
    else:
        ar = ret.sub(ret[BENCH], axis=0).drop(columns=[BENCH])
    open_days = list(ar.index)
    pos = {d: i for i, d in enumerate(open_days)}
    media = load_media_days(since)

    ev = []
    for r in mops.itertuples(index=False):
        eff, _ = news_align.effective_date(r.submitted_at.to_pydatetime(), open_days, 'TW')
        for tk in set(r.tickers):
            if tk in ar.columns:
                ev.append({'stock_id': tk, 'eff': eff, 'cat': r.cat, 'after_close': r.submitted_at.time() >= CLOSE_TW})
    ev = pd.DataFrame(ev).drop_duplicates(['stock_id', 'eff', 'cat'])

    # 每檔自身無事件日 |AR| 基準（任何類別公告的 [-1,+1] 以外）
    ev_days = {(r.stock_id, open_days[pos[r.eff] + k]) for r in ev.itertuples(index=False) if r.eff in pos
               for k in (-1, 0, 1) if 0 <= pos[r.eff] + k < len(open_days)}
    base = {}
    for c in ar.columns:
        s = ar[c].dropna()
        s = s[s.index >= since]
        v = [abs(x) for d, x in s.items() if (c, d) not in ev_days]
        base[c] = float(np.mean(v)) if v else np.nan

    recs = []
    for e in ev.itertuples(index=False):
        if e.eff not in pos:
            continue
        i = pos[e.eff]
        if i - PRE < 0 or i + POST >= len(open_days):
            continue
        seg = ar[e.stock_id].values[i - PRE:i + POST + 1]
        if np.isnan(seg).any():
            continue
        recs.append({'stock_id': e.stock_id, 'eff': e.eff, 'i': i, 'cat': e.cat, 'after_close': e.after_close,
                     'has_media': (e.stock_id, e.eff) in media,
                     'ar0': seg[PRE], 'rel0': abs(seg[PRE]) / base[e.stock_id],
                     'rel_m1': abs(seg[PRE - 1]) / base[e.stock_id],
                     'car15': seg[PRE + 1:PRE + 6].sum(), 'car120': seg[PRE + 1:].sum(),
                     'pre_car': seg[:PRE].sum()})
    st = pd.DataFrame(recs)
    # 同一檔同類別 20 日內連續公告（台積電子公司每週買賣債券、凱基金每月盈餘）視窗重疊，CAR 的 t 值會虛高：
    # 標記「不重疊」子集（同 (股票, 類別) 事件間隔 ≥ POST+1 個交易日才保留），CAR 統計只用它
    st = st.sort_values(['stock_id', 'cat', 'i'])
    keep, last = [], {}
    for r in st.itertuples(index=False):
        k = (r.stock_id, r.cat)
        ok = k not in last or r.i - last[k] > POST
        keep.append(ok)
        if ok:
            last[k] = r.i
    st['nonoverlap'] = keep
    return {'mops': mops, 'st': st.reset_index(drop=True), 'n_media_days': len(media), 'ar': ar, 'bench': bench}


def calendar_time(ar: pd.DataFrame, ev: pd.DataFrame, hold: int = POST) -> tuple:
    """單邊日曆時間投資組合：每天等權持有「事件後 1..hold 日內」的股票，t 值來自日序列（處理跨股票同日叢集）。"""
    acc = pd.DataFrame(0.0, index=ar.index, columns=['sum', 'n'])
    for e in ev.itertuples(index=False):
        seg = ar[e.stock_id].iloc[e.i + 1:e.i + 1 + hold].dropna()
        acc.loc[seg.index, 'sum'] += seg.values
        acc.loc[seg.index, 'n'] += 1
    port = (acc['sum'] / acc['n'].replace(0, np.nan)).dropna()
    if len(port) < 10:
        return float('nan'), float('nan'), len(port)
    return port.mean() * hold, float(port.mean() / (port.std(ddof=1) / math.sqrt(len(port)))), len(port)


def report(res: dict, since: date) -> str:
    mops, st = res['mops'], res['st']
    L = ['# MOPS 重大訊息分類與事件研究（Iteration 39，方案階段 3）', '',
         f'產出 {datetime.now():%Y-%m-%d %H:%M}。公告 {len(mops):,} 則（{since} 起、有個股標記），規則分類 {len(RULES) + 1} 類，'
         f'事件 {len(st):,} 個（股票 × 交易日 × 類別）。AR = 個股 − ' + ('其他追蹤股等權均值（0050 由台積電主導、有共同漂移，不用）' if res['bench'] == 'ew' else BENCH) + '，|AR₀| 以該股自身無公告日 |AR| 為 1。', '',
         '## 分類分布', '', '| 類別 | 例行 | 公告數 | 占比 | 例子 |', '|------|------|-------|------|------|']
    cnt = mops.cat.value_counts()
    for cat, n in cnt.items():
        ex = re.sub(r'^.*?（\d{4,6}）', '', mops[mops.cat == cat].title.iloc[0])[:40]
        L.append(f'| {cat} | {"是" if EXPECTED[cat] else "否"} | {n:,} | {n / len(mops):.1%} | {ex} |')
    L += ['', f'收盤後發布占 {st.after_close.mean():.0%}（歸下一交易日）。', '']

    def block(title, groups, min_n=15):
        out = [f'## {title}', '',
               '| 分組 | n | AR₀ | t | \\|AR₀\\| ÷ 基準 | \\|AR₋₁\\| ÷ 基準 | 當天有媒體 | n 不重疊 | CAR[1,5] | CAR[1,20] | t(CAR[1,20]) |',
               '|------|---|-----|---|-------------|--------------|-----------|---------|----------|-----------|-------------|']
        for name, g in groups:
            if len(g) < min_n:
                continue
            u = g[g.nonoverlap]
            out.append(f'| {name} | {len(g):,} | {g.ar0.mean() * 100:+.2f}% | {tstat(g.ar0):+.1f} | ×{g.rel0.mean():.2f} | '
                       f'×{g.rel_m1.mean():.2f} | {g.has_media.mean():.0%} | {len(u):,} | {u.car15.mean() * 100:+.2f}% | '
                       f'{u.car120.mean() * 100:+.2f}% | {tstat(u.car120):+.1f} |')
        return out + ['']

    order = st.groupby('cat').size().sort_values(ascending=False).index
    L += block('各類別（全部事件）', [(c, st[st.cat == c]) for c in order])
    st['exp'] = st.cat.map(EXPECTED)
    L += block('例行 vs 非例行', [('例行', st[st.exp]), ('非例行', st[~st.exp])])
    L += ['日曆時間投資組合（每天等權持有事件後 1~20 日內的股票；t 值來自日序列，處理跨股票同日叢集）：', '',
          '| 分組 | 20 日期間 AR | t | 交易日數 |', '|------|-----------|---|---------|']
    for name, g in [('例行', st[st.exp]), ('非例行', st[~st.exp]),
                    ('非例行・當天沒有媒體', st[~st.exp & ~st.has_media]),
                    ('併購投資 + 澄清媒體 + 其他', st[st.cat.isin(['併購投資', '澄清媒體', '其他'])])]:
        r, t, n = calendar_time(res['ar'], g)
        L.append(f'| {name} | {r * 100:+.2f}% | {t:+.1f} | {n} |')
    L.append('')
    if res['n_media_days']:
        nm = st[~st.has_media]
        L += block('當天沒有媒體新聞的公告（市場只從 MOPS 得知）', [(c, nm[nm.cat == c]) for c in order] +
                   [('例行', nm[nm.exp]), ('非例行', nm[~nm.exp])])
    L += ['## 判讀', '',
          '- **|AR₀| ÷ 基準 明顯 > 1 且 |AR₋₁| ÷ 基準 ≈ 1** 的類別：公告本身帶資訊、時間戳對得上。',
          '- **|AR₋₁| 也高**：事件在公告前就被交易（董事會決議類常見——會議當天下午公告，盤中已有消息）。',
          '- **例行類 AR₀ ≈ 0、|AR₀| ≈ 基準**：這些公告不該進模型，只會稀釋訊號；M2 用 `news_llm_feature.is_expected` 過濾。',
          '- 「當天沒有媒體新聞」那組是最乾淨的測試：若非例行類在這組仍有 |AR₀| 放大，MOPS 是獨立於媒體的資訊源。', '']
    return '\n'.join(L)


def main():
    warnings.filterwarnings('ignore')
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', default='2023-09-01')
    ap.add_argument('--no-persist', action='store_true')
    ap.add_argument('--bench', default='ew', choices=['ew', '0050'])
    a = ap.parse_args()
    since = date.fromisoformat(a.since)
    res = build(since, a.bench)
    if not a.no_persist:
        n = persist(res['mops'])
        print(f'news_llm_feature（{MODEL}）寫入 {n:,} 則')
    md = report(res, since)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(md)
    print(md)
    print(f'\n→ {os.path.abspath(OUT)}')


if __name__ == '__main__':
    main()
