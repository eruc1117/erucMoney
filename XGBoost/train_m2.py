"""
M2 新聞特派員 — XGBoost 訓練與走查（Iteration 38 重寫）

舊版（Iteration 12）只有一次 80/20 切分、樣本不足就不部署，而且新聞日用 DATE(submitted_at)、
對所有有價格的股票建樣本。回填後有三年新聞，改成方案文件的評估設計：

  · 新聞歸屬日用 `news_align.effective_date`（13:30 前歸當日，否則下一交易日）
  · 只對追蹤股建樣本，每個交易日一列（沒新聞的日子也是樣本，特徵為 0／NULL）
  · **每季 walk-forward**：用該季之前全部資料訓練、該季測試，2024Q1 起
  · 三個對照：多數類、「昨日方向延續」、**純價格 XGBoost**（同樣的模型，只拿價格特徵）
  · 新聞特徵必須贏過純價格模型才算有效；預設只出報告，加 `--deploy` 且通過門檻才存模型檔

特徵（每 stock × 交易日一列，只用當日收盤前可得資訊）：
  價格：ret_1d（T-1 漲跌幅）、ret_5d、vol_20d、abs_ret_1d
  新聞：stock_n（本股當日 canonical 新聞數）、stock_sent、stock_sent_72h（1.0/0.6/0.3 衰減）、
        stock_kw（強效關鍵字淨命中）、stock_vol_gap（本股當日數 vs 前 7 日均）、
        mkt_n、mkt_sent、mkt_sent_72h、mops_n（當日 MOPS 公告數）
標籤：T 收盤起 3 個交易日報酬 > +1.5% Buy / < −1.5% Sell / 其餘 Hold

用法：
    python train_m2.py                 # 走查 + 報告（不部署）
    python train_m2.py --deploy        # 通過門檻才存 saved_models/m2_news_xgb.joblib
    python train_m2.py --since 2023-09-01
"""

import argparse
import os
import sys
import warnings
from datetime import date, datetime

import numpy as np
import pandas as pd

CRAWLER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Crawler')
sys.path.insert(0, CRAWLER_DIR)

from db.connection import get_conn                          # noqa: E402
from model2_news import _score_text, _strong_keyword_hits   # noqa: E402
import news_align                                            # noqa: E402

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH  = os.path.join(BASE_DIR, 'saved_models', 'm2_news_xgb.joblib')
REPORT_PATH = os.path.join(BASE_DIR, 'results', 'm2_metrics.md')

PRICE_COLS = ['ret_1d', 'ret_5d', 'vol_20d', 'abs_ret_1d']
NEWS_COLS  = ['stock_n', 'stock_sent', 'stock_sent_72h', 'stock_kw', 'stock_vol_gap',
              'mkt_n', 'mkt_sent', 'mkt_sent_72h', 'mops_n']
FEATURE_COLS = PRICE_COLS + NEWS_COLS
LABEL_MAP = {0: 'Sell', 1: 'Hold', 2: 'Buy'}
BUY_TH, SELL_TH = 0.015, -0.015
HORIZON = 3
DECAY = [1.0, 0.6, 0.3]
FIRST_TEST_QUARTER = '2024Q1'


# ── 資料 ──────────────────────────────────────────────────────────────────────
def load_tracked() -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stock_id FROM stock_info WHERE is_tracking ORDER BY 1")
            return [r[0] for r in cur.fetchall()]


def load_prices(stocks: list, since: date) -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql("""
            SELECT stock_id, trade_date, COALESCE(adj_close, close_price)::float AS close
            FROM stock_daily_prices WHERE stock_id = ANY(%s) AND trade_date >= %s
            ORDER BY stock_id, trade_date
        """, conn, params=(stocks, since))
    df = df[df['close'] > 0]
    out = []
    for sid, g in df.groupby('stock_id'):
        g = g.sort_values('trade_date').reset_index(drop=True)
        r = np.log(g['close']).diff()
        g['ret_1d'] = r.shift(0)                       # 當日報酬（用於 T-1 特徵時再 shift）
        g['fwd_ret'] = g['close'].shift(-HORIZON) / g['close'] - 1
        # 特徵只能用 T-1 以前：全部 shift(1)
        g['ret_1d'] = r.shift(1)
        g['ret_5d'] = r.rolling(5).sum().shift(1)
        g['vol_20d'] = r.rolling(20).std().shift(1)
        g['abs_ret_1d'] = g['ret_1d'].abs()
        out.append(g)
    return pd.concat(out, ignore_index=True)


def load_news(since: date) -> pd.DataFrame:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name='user_news' AND column_name='is_canonical'")
            canon = 'AND is_canonical' if cur.fetchone() else ''
        df = pd.read_sql(f"""
            SELECT id, platform, title, content, submitted_at, tickers FROM user_news
            WHERE submitted_at >= %s {canon} ORDER BY submitted_at
        """, conn, params=(since,))
    text = df['title'].fillna('') + ' ' + df['content'].fillna('')
    df['sent'] = text.map(_score_text)
    df['kw'] = text.map(lambda t: (lambda h: len(h['pos']) - len(h['neg']))(_strong_keyword_hits(t)))
    df['tickers'] = df['tickers'].map(lambda t: list(t) if isinstance(t, (list, tuple)) else [])
    df['is_mops'] = df['platform'].eq('MOPS重大訊息')
    return df


def build_features(news: pd.DataFrame, prices: pd.DataFrame, stocks: list) -> pd.DataFrame:
    open_days = sorted(prices['trade_date'].unique())
    news['eff'] = news['submitted_at'].map(lambda t: news_align.effective_date(t.to_pydatetime(), open_days, 'TW')[0])

    # 全市場每日
    mkt = news.groupby('eff').agg(mkt_n=('sent', 'size'), mkt_sent=('sent', 'mean'))
    mkt = mkt.reindex(open_days).fillna({'mkt_n': 0})
    mkt['mkt_sent_72h'] = _decay(mkt['mkt_sent'], mkt['mkt_n'])

    # 個股每日（展開 tickers）
    ex = news[['eff', 'sent', 'kw', 'is_mops', 'tickers']].explode('tickers').dropna(subset=['tickers'])
    ex = ex[ex['tickers'].isin(stocks)]
    st = ex.groupby(['tickers', 'eff']).agg(stock_n=('sent', 'size'), stock_sent=('sent', 'mean'),
                                            stock_kw=('kw', 'sum'), mops_n=('is_mops', 'sum'))

    frames = []
    for sid in stocks:
        g = st.xs(sid, level=0) if sid in st.index.get_level_values(0) else pd.DataFrame()
        g = g.reindex(open_days)
        g['stock_n'] = g['stock_n'].fillna(0)
        g['mops_n'] = g['mops_n'].fillna(0)
        g['stock_kw'] = g['stock_kw'].fillna(0)
        g['stock_sent_72h'] = _decay(g['stock_sent'], g['stock_n'])
        past7 = g['stock_n'].shift(1).rolling(7, min_periods=1).mean()
        g['stock_vol_gap'] = (g['stock_n'] - past7) / past7.clip(lower=1.0)
        g['stock_id'] = sid
        g = g.join(mkt[['mkt_n', 'mkt_sent', 'mkt_sent_72h']])
        g.index.name = 'trade_date'
        frames.append(g.reset_index())
    feat = pd.concat(frames, ignore_index=True)
    data = prices.merge(feat, on=['stock_id', 'trade_date'], how='left')
    data = data.dropna(subset=PRICE_COLS + ['fwd_ret'])
    data['label'] = np.select([data['fwd_ret'] > BUY_TH, data['fwd_ret'] < SELL_TH], [2, 0], 1)
    data['quarter'] = pd.PeriodIndex(pd.to_datetime(data['trade_date']), freq='Q').astype(str)
    return data


def _decay(sent: pd.Series, n: pd.Series) -> pd.Series:
    """近 3 個交易日的加權情緒（權重 × 當日則數），沒有新聞的日子不算。"""
    num = pd.Series(0.0, index=sent.index)
    den = pd.Series(0.0, index=sent.index)
    for lag, w in enumerate(DECAY):
        s, c = sent.shift(lag), n.shift(lag).fillna(0)
        num += (s.fillna(0) * c * w)
        den += (c * w)
    return (num / den.replace(0, np.nan))


# ── 走查 ──────────────────────────────────────────────────────────────────────
def _fit(train: pd.DataFrame, cols: list):
    from xgboost import XGBClassifier
    m = XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8,
                      colsample_bytree=0.8, objective='multi:softprob', num_class=3,
                      random_state=42, n_jobs=4)
    m.fit(train[cols].fillna(0), train['label'])
    return m


def _metrics(y, p, fwd) -> dict:
    from sklearn.metrics import f1_score
    y, p, fwd = np.asarray(y), np.asarray(p), np.asarray(fwd)
    out = {'acc': float((y == p).mean()), 'f1': float(f1_score(y, p, average='macro', zero_division=0))}
    act = p != 1
    out['trade_rate'] = float(act.mean())
    # 出手時的方向正確率與平均報酬（Buy 拿正報酬、Sell 拿負報酬）
    if act.any():
        sign = np.where(p[act] == 2, 1, -1)
        out['dir_acc'] = float((np.sign(fwd[act]) == sign).mean())
        out['pnl'] = float((fwd[act] * sign).mean())
    else:
        out['dir_acc'] = out['pnl'] = float('nan')
    return out


def walk_forward(data: pd.DataFrame) -> pd.DataFrame:
    quarters = sorted(q for q in data['quarter'].unique() if q >= FIRST_TEST_QUARTER)
    rows = []
    for q in quarters:
        tr, te = data[data['quarter'] < q], data[data['quarter'] == q]
        if len(tr) < 500 or len(te) < 50:
            continue
        m_price = _fit(tr, PRICE_COLS)
        m_news = _fit(tr, FEATURE_COLS)
        p_price = m_price.predict(te[PRICE_COLS].fillna(0))
        p_news = m_news.predict(te[FEATURE_COLS].fillna(0))
        majority = int(tr['label'].mode()[0])
        p_major = np.full(len(te), majority)
        p_yday = np.select([te['ret_1d'] > BUY_TH, te['ret_1d'] < SELL_TH], [2, 0], 1)
        for name, p in [('多數類', p_major), ('昨日延續', p_yday), ('純價格', p_price), ('價格+新聞', p_news)]:
            rec = {'quarter': q, 'n': len(te), 'model': name}
            rec.update(_metrics(te['label'], p, te['fwd_ret']))
            rows.append(rec)
        print(f'{q}  train {len(tr):6d}  test {len(te):5d}  '
              + '  '.join(f'{r["model"]} acc={r["acc"]:.3f}' for r in rows[-4:]), flush=True)
    return pd.DataFrame(rows)


def report(res: pd.DataFrame, data: pd.DataFrame, imp: pd.Series, deployed: bool) -> str:
    agg = res.groupby('model').agg(acc=('acc', 'mean'), f1=('f1', 'mean'), dir_acc=('dir_acc', 'mean'),
                                   pnl=('pnl', 'mean'), trade_rate=('trade_rate', 'mean'))
    order = ['多數類', '昨日延續', '純價格', '價格+新聞']
    agg = agg.reindex(order)
    wins = (res.pivot(index='quarter', columns='model', values='f1')
               .pipe(lambda p: (p['價格+新聞'] > p['純價格']).sum()))
    lines = ['# M2 新聞模型（XGBoost）走查報告', '',
             f'**時間：** {datetime.now():%Y-%m-%d %H:%M}',
             f'**樣本：** {len(data):,}（{data["stock_id"].nunique()} 檔 × 交易日，{data["trade_date"].min()} ~ {data["trade_date"].max()}）',
             f'**走查：** 每季一折、{res["quarter"].nunique()} 折（{res["quarter"].min()} ~ {res["quarter"].max()}），用該季之前全部資料訓練',
             f'**標籤分布：** ' + '、'.join(f'{LABEL_MAP[k]} {v:.1%}' for k, v in data['label'].value_counts(normalize=True).sort_index().items()),
             '', '## 折平均', '',
             '| 模型 | Accuracy | Macro F1 | 出手率 | 出手方向正確率 | 出手平均報酬 |',
             '|------|---------|---------|-------|-------------|------------|']
    for name, r in agg.iterrows():
        lines.append(f'| {name} | {r.acc:.3f} | {r.f1:.3f} | {r.trade_rate:.1%} | {r.dir_acc:.3f} | {r.pnl * 100:+.2f}% |')
    lines += ['', f'價格+新聞 的 Macro F1 在 {wins}/{res["quarter"].nunique()} 折贏過純價格。', '',
              '## 逐季', '', '| 季 | n | 純價格 acc | 價格+新聞 acc | 純價格 F1 | 價格+新聞 F1 | 價格+新聞 出手報酬 |',
              '|----|---|----------|------------|---------|-----------|--------------|']
    piv = res.set_index(['quarter', 'model'])
    for q in sorted(res['quarter'].unique()):
        a, b = piv.loc[(q, '純價格')], piv.loc[(q, '價格+新聞')]
        lines.append(f'| {q} | {int(a.n)} | {a.acc:.3f} | {b.acc:.3f} | {a.f1:.3f} | {b.f1:.3f} | {b.pnl * 100:+.2f}% |')
    lines += ['', '## 特徵重要度（最後一折的價格+新聞模型）', '']
    lines += [f'- {k}: {v:.4f}' for k, v in imp.sort_values(ascending=False).items()]
    lines += ['', '## 部署', '',
              ('✅ 已存模型檔' if deployed else '未部署（預設只出報告；加 `--deploy` 且新聞版 F1 與出手報酬都贏過純價格才存檔）')]
    return '\n'.join(lines)


def main():
    warnings.filterwarnings('ignore')
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', default='2023-08-01')
    ap.add_argument('--deploy', action='store_true')
    a = ap.parse_args()
    since = date.fromisoformat(a.since)

    stocks = load_tracked()
    prices = load_prices(stocks, since)
    news = load_news(since)
    print(f'追蹤股 {len(stocks)}，價格列 {len(prices):,}，新聞 {len(news):,} 則')
    data = build_features(news, prices, stocks)
    print(f'樣本 {len(data):,}，標籤 {data["label"].map(LABEL_MAP).value_counts().to_dict()}')

    res = walk_forward(data)
    if res.empty:
        print('沒有可走查的季度'); return

    last_q = res['quarter'].max()
    final = _fit(data[data['quarter'] <= last_q], FEATURE_COLS)
    imp = pd.Series(final.feature_importances_, index=FEATURE_COLS)

    agg = res.groupby('model').agg(f1=('f1', 'mean'), pnl=('pnl', 'mean'))
    passed = bool(agg.loc['價格+新聞', 'f1'] > agg.loc['純價格', 'f1'] and
                  agg.loc['價格+新聞', 'pnl'] > agg.loc['純價格', 'pnl'])
    deployed = False
    if a.deploy and passed:
        import joblib
        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
        joblib.dump({'model': final, 'feature_cols': FEATURE_COLS, 'label_map': LABEL_MAP,
                     'trained_at': datetime.now().isoformat(),
                     'thresholds': {'buy': BUY_TH, 'sell': SELL_TH}, 'version': 'iter38'}, MODEL_PATH)
        deployed = True
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    md = report(res, data, imp, deployed)
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(md)
    print('\n' + md)
    print(f'\n門檻{"通過" if passed else "未通過"}；{"已部署" if deployed else "未部署"}。報告：{REPORT_PATH}')


if __name__ == '__main__':
    main()
