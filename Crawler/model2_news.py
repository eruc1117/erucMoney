"""
模型二：新聞特派員（時序滯後影響模型 — 訊息驅動）
─────────────────────────────────────────────────
架構：雙階段
  階段 A（特徵工程）：對每篇新聞計算 Sentiment_Score，並加入時間衰減權重
  階段 B（規則評分）：以加權特徵矩陣輸出 Buy / Sell / Hold 信號

特徵矩陣：
  Avg_Sentiment_72h      過去 72 小時情緒移動平均（時間衰減）
  News_Volume_Gap        今日新聞量 vs 7 日均量差值（爆量 = 轉折信號）
  Keyword_Recovery_Hit   強效關鍵詞命中數（Demand Recovery / Gross Margin 等）
  Price_Return_T1        昨日漲跌幅（判斷新聞是否已被市場反應）
  Sector_Sentiment       同產業（電子股）近 24 小時整體情緒均值

時間衰減權重（Time Decay）：
  T+0（今日）    1.0
  T+1（昨日）    0.6
  T+2（前天）    0.3
  T+3 以後       忽略
"""

import logging
from datetime import datetime, timedelta, date, timezone

from db.connection import get_conn

logger = logging.getLogger(__name__)

# ── 正負情緒關鍵字 ─────────────────────────────────────────────────────────
POS_WORDS = [
    # 中文
    '上漲', '漲', '獲利', '盈餘', '成長', '創新高', '突破', '看漲', '買超', '利多',
    '增加', '強勁', '回升', '反彈', '樂觀', '超越', '優於', '亮眼', '加速', '擴大',
    '需求回溫', '庫存去化', '產能滿載', '法說會利多', '營收創高',
    # 英文
    'growth', 'profit', 'rise', 'gain', 'bull', 'strong', 'increase', 'beat',
    'upgrade', 'rally', 'surge', 'record', 'positive', 'opportunity',
    'demand recovery', 'inventory depletion', 'capacity utilization',
]
NEG_WORDS = [
    # 中文
    '下跌', '跌', '虧損', '衰退', '創新低', '跌破', '看跌', '賣超', '利空',
    '減少', '疲軟', '下滑', '走弱', '悲觀', '低於', '警訊', '放緩', '縮小', '壓力',
    '毛利率下滑', '庫存回升', '砍單', '降評', '財報雷',
    # 英文
    'loss', 'decline', 'fall', 'drop', 'bear', 'weak', 'decrease', 'miss',
    'downgrade', 'crash', 'negative', 'risk', 'warning', 'layoff', 'sanctions',
]

# 強效電子股關鍵字（命中即給額外加分）
STRONG_POS_KEYWORDS = [
    'demand recovery', 'inventory depletion', 'capacity utilization',
    '需求回溫', '庫存去化', '產能利用率', '毛利率提升', 'gross margin',
    'revenue', '營收', 'conference', '法說會',
]
STRONG_NEG_KEYWORDS = [
    'sanctions', '禁令', '財報雷', '砍單', 'downgrade',
    'gross margin decline', '毛利率下滑', 'inventory build',
]

# 時間衰減權重
DECAY_WEIGHTS = {0: 1.0, 1: 0.6, 2: 0.3}


def _days_ago(ts: datetime) -> int:
    """計算文章距今幾天（0=今天, 1=昨天, 2=前天）"""
    now = datetime.now(timezone.utc) if ts.tzinfo else datetime.now()
    return (now.date() - ts.date()).days


def _score_text(text: str) -> float:
    """對單篇文字計算情緒分數（-1.0 ~ +1.0）"""
    lower = text.lower()
    pos = sum(1 for w in POS_WORDS if w in lower)
    neg = sum(1 for w in NEG_WORDS if w in lower)
    total = pos + neg
    if total == 0:
        return 0.0
    return round((pos - neg) / total, 4)


def _strong_keyword_hits(text: str) -> dict:
    """回傳強效關鍵字命中結果"""
    lower = text.lower()
    return {
        'pos': [kw for kw in STRONG_POS_KEYWORDS if kw in lower],
        'neg': [kw for kw in STRONG_NEG_KEYWORDS if kw in lower],
    }


def _fetch_news(hours: int = 72) -> list:
    """取得近 N 小時所有新聞（不限股票）"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT title, content, submitted_at, tickers
                FROM user_news
                WHERE submitted_at >= NOW() - INTERVAL '72 hours'
                ORDER BY submitted_at DESC
                LIMIT 200
            """)
            rows = cur.fetchall()
    return [
        {
            'title':        r[0] or '',
            'content':      r[1] or '',
            'submitted_at': r[2],
            'tickers':      r[3] or [],
        }
        for r in rows
    ]


def _fetch_price_return(stock_id: str) -> float:
    """取得昨日漲跌幅（Price_Return_T_Minus_1）"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT change_rate FROM stock_daily_prices
                WHERE stock_id = %s AND change_rate IS NOT NULL
                ORDER BY trade_date DESC LIMIT 1
            """, (stock_id,))
            row = cur.fetchone()
    return float(row[0]) if row else 0.0


def _compute_features(articles: list, stock_id: str) -> dict:
    """
    計算特徵矩陣：
      avg_sentiment_72h   時間衰減加權情緒均值
      news_volume_gap     今日文章數 vs 7日均量差異（標準化）
      keyword_recovery_hit 強效關鍵字命中總分
      price_return_t1     昨日漲跌幅
      sector_sentiment    全部文章整體情緒均值
      stock_articles      與本股票相關的文章數
    """
    if not articles:
        return {
            'avg_sentiment_72h':    0.0,
            'news_volume_gap':      0.0,
            'keyword_recovery_hit': 0,
            'strong_pos_keywords':  [],
            'strong_neg_keywords':  [],
            'price_return_t1':      _fetch_price_return(stock_id),
            'sector_sentiment':     0.0,
            'total_articles':       0,
            'stock_articles':       0,
        }

    # ── 時間衰減加權情緒 ──────────────────────────────────────────────────
    weighted_scores, weights_sum = [], 0.0
    for a in articles:
        d = _days_ago(a['submitted_at'])
        w = DECAY_WEIGHTS.get(d, 0.0)
        if w == 0:
            continue
        text = a['title'] + ' ' + a['content']
        s = _score_text(text) * w
        weighted_scores.append(s)
        weights_sum += w

    avg_sentiment = round(sum(weighted_scores) / weights_sum, 4) if weights_sum > 0 else 0.0

    # ── 今日文章量 vs 7日均量 ─────────────────────────────────────────────
    today = date.today()
    today_count = sum(1 for a in articles if _days_ago(a['submitted_at']) == 0)
    # 近 3 天均量（作為基準）
    past_count  = sum(1 for a in articles if 1 <= _days_ago(a['submitted_at']) <= 3)
    daily_avg   = past_count / 3 if past_count > 0 else 1
    volume_gap  = round((today_count - daily_avg) / max(daily_avg, 1), 3)

    # ── 強效關鍵字命中 ────────────────────────────────────────────────────
    all_text = ' '.join(a['title'] + ' ' + a['content'] for a in articles
                        if _days_ago(a['submitted_at']) <= 1)
    hits = _strong_keyword_hits(all_text)
    recovery_score = len(hits['pos']) - len(hits['neg'])

    # ── 整體產業情緒（全部文章均值）─────────────────────────────────────
    all_scores = [_score_text(a['title'] + ' ' + a['content']) for a in articles]
    sector_sentiment = round(sum(all_scores) / len(all_scores), 4) if all_scores else 0.0

    # ── 本股票專屬特徵（Iteration 10 新增）────────────────────────────────
    # 舊版只算 stock_articles 卻從未在評分中使用，五項評分輸入有四項是全市場
    # 聚合值 → 22 檔股票必然拿到完全相同的訊號。這是「全 Buy」的結構性根因。
    own = [a for a in articles if stock_id in (a['tickers'] or [])]
    own_weighted, own_wsum = [], 0.0
    for a in own:
        w = DECAY_WEIGHTS.get(_days_ago(a['submitted_at']), 0.0)
        if w == 0:
            continue
        own_weighted.append(_score_text(a['title'] + ' ' + a['content']) * w)
        own_wsum += w
    stock_sentiment = round(sum(own_weighted) / own_wsum, 4) if own_wsum > 0 else 0.0

    own_hits = _strong_keyword_hits(' '.join(a['title'] + ' ' + a['content'] for a in own))
    stock_keyword_score = len(own_hits['pos']) - len(own_hits['neg'])

    return {
        'avg_sentiment_72h':    avg_sentiment,
        'news_volume_gap':      volume_gap,
        'keyword_recovery_hit': recovery_score,
        'strong_pos_keywords':  hits['pos'],
        'strong_neg_keywords':  hits['neg'],
        'price_return_t1':      _fetch_price_return(stock_id),
        'sector_sentiment':     sector_sentiment,
        'total_articles':       len(articles),
        'stock_articles':       len(own),
        'stock_sentiment_72h':  stock_sentiment,
        'stock_keyword_hit':    stock_keyword_score,
        'stock_pos_keywords':   own_hits['pos'],
        'stock_neg_keywords':   own_hits['neg'],
    }


def _features_to_signal(f: dict) -> tuple:
    """
    規則評分器（XGBoost 的規則替代，待訓練資料足夠後替換）。

    Iteration 10 結構性修正：以**本股票自己的新聞**為評分主體。
    舊版五項輸入有四項是全市場聚合值，導致 22 檔股票恆得相同訊號；
    本股票文章數雖有計算卻從未使用。

    無本股新聞時一律 Hold —— 沿用 Iteration 9 對 M3 的原則：
    沒有證據就棄權，而不是拿大盤情緒冒充個股觀點。
    投票引擎以固定 ±0.33 計分且不參考 confidence，送出即全權重。

    註：本規則權重未經回測驗證（新聞歷史僅數日，尚無法走查）。
        資料累積足夠後應以 XGBoost/train_m2.py 取代，並比較兩者表現。
    """
    n_own = f.get('stock_articles', 0)
    if n_own == 0:
        return 'Hold', 0.1

    score = 0.0

    # 1. 本股新聞的時間衰減情緒（主體，權重最高）
    score += f.get('stock_sentiment_72h', 0.0) * 2.5

    # 2. 本股強效關鍵字（法說會、毛利率、砍單等）
    score += f.get('stock_keyword_hit', 0) * 0.4

    # 3. 大盤情緒作為背景修正（輔助，權重低）
    score += f['sector_sentiment'] * 0.4

    # 4. 新聞爆量：僅在本股確實有數則新聞時才視為轉折訊號
    if n_own >= 3 and abs(f['news_volume_gap']) > 0.5:
        score += f['news_volume_gap'] * f.get('stock_sentiment_72h', 0.0) * 1.0

    # 5. 昨日漲跌幅修正（新聞是否已被市場反應）
    if f['price_return_t1'] > 3.0 and score > 0:
        score *= 0.7
    elif f['price_return_t1'] < -3.0 and score < 0:
        score *= 0.7

    # 文章數越少證據越薄弱 → 信心打折（1 篇 0.6 倍、3 篇以上不打折）
    evidence = min(n_own / 3.0, 1.0) * 0.4 + 0.6
    confidence = min(abs(score) * 0.4 + 0.2, 0.95) * evidence

    if score >= 0.4:
        return 'Buy', round(confidence, 3)
    if score <= -0.4:
        return 'Sell', round(confidence, 3)
    return 'Hold', round(max(0.1, confidence * 0.5), 3)


def _build_reason(signal: str, f: dict) -> str:
    n_own = f.get('stock_articles', 0)
    if n_own == 0:
        return (f"近 72h 共 {f['total_articles']} 篇財經新聞，但**無一篇提及本股**，"
                f"故不以大盤情緒代替個股判斷，觀望")

    parts = [f"近 72h 本股相關 {n_own} 篇（全部新聞 {f['total_articles']} 篇）",
             f"本股情緒={f.get('stock_sentiment_72h', 0.0):+.3f}",
             f"大盤情緒={f['sector_sentiment']:+.3f}"]
    if abs(f['news_volume_gap']) > 0.3:
        parts.append(f"新聞量{'爆量↑' if f['news_volume_gap'] > 0 else '冷清↓'}"
                     f"({f['news_volume_gap']:+.2f})")
    if f.get('stock_pos_keywords'):
        parts.append(f"本股利多關鍵字：{', '.join(f['stock_pos_keywords'][:3])}")
    if f.get('stock_neg_keywords'):
        parts.append(f"本股利空關鍵字：{', '.join(f['stock_neg_keywords'][:3])}")
    parts.append(f"昨收漲跌幅={f['price_return_t1']:+.2f}%")
    return '；'.join(parts)


def _persist_features(stock_id: str, f: dict) -> None:
    """將特徵寫入 news_features 表（同股票同日 upsert），供歷史回測與儀表板使用。

    Iteration 32：補上個股層級欄位。在此之前落地的只有 `avg_sentiment_72h`
    與 `total_articles` 兩個**全市場**聚合值，於是同一天所有股票的列完全相同
    ——評分明明是以本股新聞為主體（Iteration 10），個股特徵卻沒被存下來。
    對下游而言那是一個變異數恆為 0 的欄位，訓練不會報錯，只會學不到東西。

    `stock_sentiment` 在本股無新聞時寫 NULL 而非 0.0：評分端遇到這種情況是
    **棄權**（一律 Hold），0.0 會被讀成「本股有新聞、情緒中性」，意思不同。
    """
    import json
    n_own = f.get('stock_articles', 0)
    keyword_hits = {
        'pos': f.get('strong_pos_keywords', []),
        'neg': f.get('strong_neg_keywords', []),
        'recovery_score': f.get('keyword_recovery_hit', 0),
        'news_volume_gap': f.get('news_volume_gap', 0.0),
        'sector_sentiment': f.get('sector_sentiment', 0.0),
        # 以下為本股層級，與上方全市場欄位並存（評分實際使用的是這一組）
        'stock_pos': f.get('stock_pos_keywords', []),
        'stock_neg': f.get('stock_neg_keywords', []),
        'stock_keyword_hit': f.get('stock_keyword_hit', 0),
        'price_return_t1': f.get('price_return_t1', 0.0),
    }
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO news_features
                        (stock_id, feature_date, sentiment, keyword_hits, article_count,
                         stock_sentiment, stock_article_count)
                    VALUES (%s, CURRENT_DATE, %s, %s, %s, %s, %s)
                    ON CONFLICT (stock_id, feature_date) DO UPDATE SET
                        sentiment           = EXCLUDED.sentiment,
                        keyword_hits        = EXCLUDED.keyword_hits,
                        article_count       = EXCLUDED.article_count,
                        stock_sentiment     = EXCLUDED.stock_sentiment,
                        stock_article_count = EXCLUDED.stock_article_count,
                        updated_at          = CURRENT_TIMESTAMP
                """, (stock_id, f['avg_sentiment_72h'], json.dumps(keyword_hits, ensure_ascii=False),
                      f['total_articles'],
                      f.get('stock_sentiment_72h') if n_own else None,
                      n_own))
            conn.commit()
    except Exception as e:
        logger.warning('[model2/news] news_features 寫入失敗 %s: %s', stock_id, e)


# ── XGBoost 模型（train_m2.py 部署後自動啟用；缺檔即維持規則引擎）────────────

import os as _os
_XGB_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                          '..', 'XGBoost', 'saved_models', 'm2_news_xgb.joblib')
_xgb_bundle = None
_xgb_load_failed = False


def _load_xgb():
    global _xgb_bundle, _xgb_load_failed
    if _xgb_bundle is not None or _xgb_load_failed:
        return _xgb_bundle
    if not _os.path.exists(_XGB_PATH):
        _xgb_load_failed = True
        return None
    try:
        import joblib
        _xgb_bundle = joblib.load(_XGB_PATH)
        logger.info('[model2/news] XGBoost 模型已載入（trained_at=%s）',
                    _xgb_bundle.get('trained_at', '?'))
    except Exception as e:
        _xgb_load_failed = True
        logger.warning('[model2/news] XGBoost 載入失敗，使用規則引擎：%s', e)
    return _xgb_bundle


def _features_iter38(stock_id: str) -> dict:
    """
    Iteration 38 版模型的 13 個特徵，定義與 XGBoost/train_m2.py 的 build_features 一致：
    新聞歸屬日用 news_align.effective_date（13:30 前歸當日），全市場與本股各算當日與 72h 衰減，
    價格特徵只用 T-1 以前。推論日 = 今天（或今天之後第一個交易日）。
    """
    import numpy as np
    import pandas as pd
    import news_align
    from datetime import timedelta

    with get_conn() as conn:
        prices = pd.read_sql("""
            SELECT trade_date, COALESCE(adj_close, close_price)::float AS close
            FROM stock_daily_prices WHERE stock_id = %s AND trade_date >= %s ORDER BY trade_date
        """, conn, params=(stock_id, date.today() - timedelta(days=60)))
        news = pd.read_sql("""
            SELECT platform, title, content, submitted_at, tickers FROM user_news
            WHERE submitted_at >= %s
        """, conn, params=(datetime.now() - timedelta(days=14),))
    prices = prices[prices['close'] > 0]
    r = np.log(prices['close']).diff()
    f = {
        'ret_1d': float(r.iloc[-1]) if len(r) else 0.0,
        'ret_5d': float(r.tail(5).sum()),
        'vol_20d': float(r.tail(20).std()) if len(r) >= 5 else 0.0,
    }
    f['abs_ret_1d'] = abs(f['ret_1d'])

    open_days = list(prices['trade_date'])
    today = date.today()
    eff_today = today if (open_days and open_days[-1] == today) else news_align.effective_date(
        datetime.now(), open_days, 'TW')[0]
    # 推論日的「交易日序列」：歷史交易日 + 推論日
    days = sorted(set(open_days) | {eff_today})

    text = news['title'].fillna('') + ' ' + news['content'].fillna('')
    news['sent'] = text.map(_score_text)
    news['kw'] = text.map(lambda t: (lambda h: len(h['pos']) - len(h['neg']))(_strong_keyword_hits(t)))
    news['eff'] = news['submitted_at'].map(lambda t: news_align.effective_date(t.to_pydatetime(), days, 'TW')[0])
    news['own'] = news['tickers'].map(lambda t: stock_id in (t or []))
    news['mops'] = news['platform'].eq('MOPS重大訊息')

    def decay(df):
        num = den = 0.0
        for lag, w in enumerate(DECAY_WEIGHTS.values()):
            idx = days.index(eff_today) - lag
            if idx < 0:
                break
            d = df[df['eff'] == days[idx]]
            if len(d):
                num += d['sent'].mean() * len(d) * w
                den += len(d) * w
        return num / den if den else np.nan

    mk = news[news['eff'] == eff_today]
    own = news[news['own']]
    own_today = own[own['eff'] == eff_today]
    i = days.index(eff_today)
    past7 = [int((own['eff'] == days[i - k]).sum()) for k in range(1, 8) if i - k >= 0]
    base = max(float(np.mean(past7)) if past7 else 0.0, 1.0)
    f.update({
        'stock_n': len(own_today),
        'stock_sent': float(own_today['sent'].mean()) if len(own_today) else np.nan,
        'stock_sent_72h': decay(own),
        'stock_kw': int(own_today['kw'].sum()),
        'stock_vol_gap': (len(own_today) - base) / base,
        'mkt_n': len(mk),
        'mkt_sent': float(mk['sent'].mean()) if len(mk) else np.nan,
        'mkt_sent_72h': decay(news),
        'mops_n': int(own_today['mops'].sum()),
    })
    return f


def _xgb_signal(articles: list, f: dict) -> tuple | None:
    """以 XGBoost 推論；模型缺檔或失敗回 None（呼叫端 fallback 規則引擎）。"""
    bundle = _load_xgb()
    if bundle is None:
        return None
    if bundle.get('version') == 'iter38':
        try:
            import numpy as np
            feats = _features_iter38(f['_stock_id'])
            x = np.array([[np.nan_to_num(feats[c], nan=0.0) for c in bundle['feature_cols']]])
            proba = bundle['model'].predict_proba(x)[0]
            cls = int(proba.argmax())
            f['xgb_features'] = {k: (None if isinstance(v, float) and v != v else v) for k, v in feats.items()}
            return bundle['label_map'][cls], round(float(proba[cls]), 3)
        except Exception as e:
            logger.warning('[model2/news] iter38 XGBoost 推論失敗，fallback 規則：%s', e)
            return None
    try:
        today_scores = [_score_text(a['title'] + ' ' + a['content'])
                        for a in articles if _days_ago(a['submitted_at']) == 0]
        avg_24h = round(sum(today_scores) / len(today_scores), 4) if today_scores else 0.0
        x = [[
            avg_24h,
            f['avg_sentiment_72h'],
            f['news_volume_gap'],
            f['keyword_recovery_hit'],
            f['stock_articles'],
            f['price_return_t1'],
            f['sector_sentiment'],
        ]]
        proba = bundle['model'].predict_proba(x)[0]
        cls = int(proba.argmax())
        return bundle['label_map'][cls], round(float(proba[cls]), 3)
    except Exception as e:
        logger.warning('[model2/news] XGBoost 推論失敗，fallback 規則：%s', e)
        return None


def get_signal(stock_id: str) -> dict:
    """
    模型二主入口。
    Returns: { stock_id, signal, confidence, reason, features }
    """
    articles = _fetch_news(hours=72)
    features = _compute_features(articles, stock_id)
    features['_stock_id'] = stock_id      # iter38 XGBoost 推論需要

    xgb = _xgb_signal(articles, features)
    if xgb is not None:
        signal, confidence = xgb
    else:
        signal, confidence = _features_to_signal(features)
    reason = _build_reason(signal, features)
    _persist_features(stock_id, features)

    logger.info('[model2/news] %s → %s (conf=%.2f) sentiment=%.3f vol_gap=%.2f kw=%+d',
                stock_id, signal, confidence,
                features['avg_sentiment_72h'],
                features['news_volume_gap'],
                features['keyword_recovery_hit'])

    return {
        'stock_id':   stock_id,
        'signal':     signal,
        'confidence': confidence,
        'reason':     reason,
        'features':   features,
    }
