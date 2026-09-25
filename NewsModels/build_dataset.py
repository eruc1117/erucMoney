"""
建資料集：新聞（打標到 181 檔）+ 價格面板 + 樣本（股票 × 有新聞的交易日）

輸出（NewsModels/data/）
    news.pkl      每則新聞一列：id, platform, tier, title, content, submitted_at, eff（歸屬交易日）, tickers（宇宙內）, sent（字典分數）
    panel.pkl     每檔每交易日一列：價格特徵、當日新聞聚合（n、sent_mean、sent_min、sent_max、n_tier1、n_mops、attn）
    samples.pkl   panel 中「當日有新聞」且標籤可算的列，附 news_ids
    open_days.pkl 交易日清單

打標：user_news.tickers 只標了 26 檔追蹤股（rss_news_scraper 用 stock_info 比對），研究股要在這裡補：
公司名（FinMind TaiwanStockInfo，去星號、長度 ≥ 2）或「（代號）」出現在標題／內文前 2,000 字。
不寫回 user_news——這只是研究用的標記。

標籤（相對股票池等權均值的超額 log 報酬）：
    y1 = sign(excess[D+1])          預測「今天收盤買、明天收盤賣」
    y3 = sign(sum excess[D+1..D+3])
    y5 = sign(sum excess[D+1..D+5])
新聞歸屬 D 的定義沿用 news_align：13:30 前發布歸當日 D（D 收盤前已知），之後歸下一交易日。
"""
import json
import os
import re
import sys
import warnings
from datetime import date, datetime

import numpy as np
import pandas as pd

import nm_config as C
from db.connection import get_conn

warnings.filterwarnings('ignore')
CODE_RE = re.compile(r'[（(](\d{4})[)）]|(\d{4})-TW')


def universe() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stock_id FROM stock_info WHERE is_tracking AND COALESCE(industry_type,'') <> 'ETF' ORDER BY 1")
            ids = [r[0] for r in cur.fetchall()]
            cur.execute("SELECT stock_id FROM research_daily_prices GROUP BY 1 HAVING count(*) >= 200 ORDER BY 1")
            ids += [r[0] for r in cur.fetchall() if r[0] not in ids]
    return ids


def name_map(ids: list) -> dict:
    info = json.load(open(os.path.join(C.ROOT, 'stock_info_finmind.json'), encoding='utf-8'))
    m = {}
    for d in info:
        sid = str(d.get('stock_id'))
        if sid in ids and d.get('type') in ('twse', 'tpex'):
            nm = (d.get('stock_name') or '').replace('*', '').strip()
            if len(nm) >= 2:
                m[sid] = nm
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stock_id, stock_name FROM stock_info")
            for sid, nm in cur.fetchall():
                if sid in ids and nm:
                    m[sid] = nm.replace('*', '').strip()
    return m


def load_prices(ids: list) -> pd.DataFrame:
    with get_conn() as conn:
        a = pd.read_sql("""SELECT stock_id, trade_date, COALESCE(adj_close, close_price) AS px, volume, high_price, low_price, close_price
                           FROM stock_daily_prices WHERE stock_id = ANY(%s) AND trade_date >= %s""", conn, params=(ids, C.PRICE_SINCE))
        rest = [s for s in ids if s not in set(a.stock_id)]
        b = pd.read_sql("""SELECT stock_id, trade_date, close_price AS px, volume, high_price, low_price, close_price
                           FROM research_daily_prices WHERE stock_id = ANY(%s) AND trade_date >= %s""", conn, params=(rest, C.PRICE_SINCE))
    df = pd.concat([a, b], ignore_index=True)
    for c in ('px', 'volume', 'high_price', 'low_price', 'close_price'):
        df[c] = df[c].astype(float)
    return df.sort_values(['stock_id', 'trade_date'])


def price_panel(px: pd.DataFrame) -> pd.DataFrame:
    """每檔每日：log 報酬、超額報酬（− 等權均值）、動能、波動、量比、振幅；標籤 y1/y3/y5。"""
    wide = px.pivot(index='trade_date', columns='stock_id', values='px').where(lambda x: x > 0)
    ret = np.log(wide).diff().where(lambda r: r.abs() < 0.5)
    tot, cnt = ret.sum(axis=1), ret.notna().sum(axis=1)
    ew = pd.DataFrame({c: (tot - ret[c].fillna(0)) / (cnt - ret[c].notna().astype(int)).replace(0, np.nan) for c in ret.columns})
    ex = ret - ew
    vol = px.pivot(index='trade_date', columns='stock_id', values='volume')
    hi = px.pivot(index='trade_date', columns='stock_id', values='high_price')
    lo = px.pivot(index='trade_date', columns='stock_id', values='low_price')
    cl = px.pivot(index='trade_date', columns='stock_id', values='close_price')
    rng = np.log(hi / lo).where(lambda r: r < 0.3)

    feats = {
        'r1': ret, 'ex1': ex,
        'ex2': ex.rolling(2).sum(), 'ex5': ex.rolling(5).sum(), 'ex10': ex.rolling(10).sum(), 'ex20': ex.rolling(20).sum(),
        'mkt1': ew, 'mkt5': ew.rolling(5).sum(),
        'vol20': ret.rolling(20).std(), 'rng1': rng, 'rng5': rng.rolling(5).mean(),
        'vr': np.log((vol / vol.rolling(20).mean()).replace(0, np.nan)),
        'ex60': ex.rolling(60).sum(),
    }
    lab = {'y1': ex.shift(-1), 'y3': ex.shift(-1).rolling(3).sum().shift(-2), 'y5': ex.shift(-1).rolling(5).sum().shift(-4)}
    frames = []
    for k, v in {**feats, **{f'fwd_{k}': v for k, v in lab.items()}}.items():
        s = v.stack(dropna=False)
        s.name = k
        frames.append(s)
    panel = pd.concat(frames, axis=1).reset_index().rename(columns={'level_0': 'date', 'level_1': 'stock_id'})
    panel.columns = ['date', 'stock_id'] + list(panel.columns[2:])
    panel['date'] = pd.to_datetime(panel.date).dt.date
    return panel


def load_news(ids: list, names: dict) -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql("""
            SELECT id, platform, COALESCE(source_tier, 3) AS tier, title, content, submitted_at, tickers
            FROM user_news WHERE submitted_at >= %s AND COALESCE(is_canonical, TRUE)
              AND title IS NOT NULL ORDER BY submitted_at""", conn, params=(C.NEWS_SINCE,))
    idset = set(ids)
    names_sorted = sorted(names.items(), key=lambda kv: -len(kv[1]))
    out = []
    for r in df.itertuples(index=False):
        text = (r.title or '') + '\n' + (r.content or '')[:2000]
        tags = [t for t in (r.tickers or []) if t in idset]
        for m in CODE_RE.finditer(text):
            c = m.group(1) or m.group(2)
            if c in idset:
                tags.append(c)
        for sid, nm in names_sorted:
            if nm in text:
                tags.append(sid)
        tags = list(dict.fromkeys(tags))
        if not tags or len(tags) > C.MAX_TAGS:
            continue
        out.append({'id': int(r.id), 'platform': r.platform, 'tier': int(r.tier), 'title': r.title,
                    'content': (r.content or '')[:1500], 'submitted_at': r.submitted_at, 'tickers': tags})
    news = pd.DataFrame(out)
    from model2_news import _score_text
    news['sent'] = [_score_text((t or '') + ' ' + (c or '')) for t, c in zip(news.title, news.content)]
    news['is_mops'] = news.platform == 'MOPS重大訊息'
    return news


def assign_days(news: pd.DataFrame, open_days: list) -> pd.DataFrame:
    import news_align
    news['eff'] = [news_align.effective_date(ts.to_pydatetime(), open_days, 'TW')[0] for ts in news.submitted_at]
    return news


def news_aggregate(news: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in news.itertuples(index=False):
        for t in r.tickers:
            rows.append((t, r.eff, r.id, r.sent, r.tier, r.is_mops, len(r.tickers)))
    x = pd.DataFrame(rows, columns=['stock_id', 'date', 'news_id', 'sent', 'tier', 'is_mops', 'n_tags'])
    x['sent_w'] = x.sent / x.n_tags                      # 標到多檔的新聞權重降低
    g = x.groupby(['stock_id', 'date'])
    agg = g.agg(n=('news_id', 'size'), sent_mean=('sent', 'mean'), sent_min=('sent', 'min'), sent_max=('sent', 'max'),
                sent_w=('sent_w', 'sum'), n_tier1=('tier', lambda s: int((s == 1).sum())), n_mops=('is_mops', 'sum'),
                n_solo=('n_tags', lambda s: int((s == 1).sum())), news_ids=('news_id', list)).reset_index()
    p = panel.merge(agg, on=['stock_id', 'date'], how='left')
    p['n'] = p.n.fillna(0).astype(int)
    for c in ('sent_mean', 'sent_min', 'sent_max', 'sent_w'):
        p[c] = p[c].fillna(0.0)
    for c in ('n_tier1', 'n_mops', 'n_solo'):
        p[c] = p[c].fillna(0).astype(int)
    # 異常注意力：當日則數 ÷ 該股過去 60 個交易日的日均則數（Da, Engelberg & Gao 2011 的精神）
    p = p.sort_values(['stock_id', 'date'])
    base = p.groupby('stock_id').n.transform(lambda s: s.shift(1).rolling(60, min_periods=20).mean())
    p['attn'] = np.log1p(p.n) - np.log1p(base.fillna(p.n.mean()))
    p['news_ids'] = p.news_ids.apply(lambda v: v if isinstance(v, list) else [])
    return p


def main():
    t0 = datetime.now()
    ids = universe()
    names = name_map(ids)
    print(f'股票池 {len(ids)} 檔，有公司名 {len(names)}', flush=True)
    px = load_prices(ids)
    open_days = sorted(px.trade_date.unique())
    open_days = [d if isinstance(d, date) else pd.Timestamp(d).date() for d in open_days]
    panel = price_panel(px)
    print(f'價格面板 {len(panel):,} 列、交易日 {len(open_days)}', flush=True)
    news = load_news(ids, names)
    news = assign_days(news, open_days)
    print(f'新聞 {len(news):,} 則（標到股票池；含研究股補標）', flush=True)
    panel = news_aggregate(news, panel)
    panel = panel[panel.date >= C.SAMPLE_SINCE - pd.Timedelta(days=90).to_pytimedelta()]
    feat_cols = ['r1', 'ex1', 'ex2', 'ex5', 'ex10', 'ex20', 'mkt1', 'mkt5', 'vol20', 'rng1', 'rng5', 'vr', 'ex60']
    samples = panel[(panel.n > 0) & (panel.date >= C.SAMPLE_SINCE) & panel.fwd_y1.notna() & panel[feat_cols].notna().all(axis=1)].copy()
    samples = samples.reset_index(drop=True)
    for k in ('y1', 'y3', 'y5'):
        samples[k] = (samples[f'fwd_{k}'] > 0).astype(int)
    print(f'樣本 {len(samples):,}（股票 {samples.stock_id.nunique()}、{samples.date.min()} ~ {samples.date.max()}）；'
          f'y1 正類 {samples.y1.mean():.3f}', flush=True)
    news.to_pickle(os.path.join(C.DATA_DIR, 'news.pkl'))
    panel.to_pickle(os.path.join(C.DATA_DIR, 'panel.pkl'))
    samples.to_pickle(os.path.join(C.DATA_DIR, 'samples.pkl'))
    pd.to_pickle(open_days, os.path.join(C.DATA_DIR, 'open_days.pkl'))
    print(f'完成 {(datetime.now() - t0).seconds}s → {C.DATA_DIR}', flush=True)


if __name__ == '__main__':
    main()
