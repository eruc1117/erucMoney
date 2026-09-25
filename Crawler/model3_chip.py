"""
模型三：籌碼觀測員（結構驅動）

優先使用訓練好的 Random Forest（RandomForest/saved_models/m3_chip_rf.joblib，
特徵見 m3_features.py）；模型檔不存在或該股歷史不足時 fallback 至規則判斷。

Iteration 9 起模型為 v2（alpha 標籤 + 橫斷面特徵），推論有三項對應改動：

  1. 橫斷面特徵需要同日全體追蹤股票，故一次撈全部股票建面板（附快取，
     一輪投票 22 次呼叫只計算一次）。
  2. 信心門檻改由模型 bundle 的 `proba_gate` 決定，不再寫死。
     v1 寫死 0.45 而模型最高機率僅約 0.45，導致線上 22 檔全被擋下、
     永遠回 Hold —— 這個線上失效在 Iteration 9 才被發現。
  3. 依 bundle 的 `sell_policy` 決定是否放行賣出訊號。走查顯示賣出側
     方向準確率僅約 52% 且平均報酬為負，而投票引擎不參考 confidence
     （固定 ±0.33 計分），放行等同注入雜訊，故預設抑制為 Hold。

舊版 bundle（無這些欄位）會退回 v1 行為，仍可運作。

**規則 fallback 預設停用（Iteration 9）**
evaluate_rule_fallback.py 在 22 檔全歷史（28,886 筆）上實測規則引擎：
方向準確率 48.31%，比擲硬幣還差，且它從不輸出 Hold——每天對每檔都以
±0.33 全權重投票。RF 無法推論時改為棄權（Hold）優於送出負 edge 的訊號。
需比較時可設環境變數 M3_RULE_FALLBACK=allow 恢復舊行為。
"""
import logging
import os
from db.connection import get_conn

logger = logging.getLogger(__name__)

# 'abstain'（預設）：RF 不可用時回 Hold；'allow'：使用規則引擎（實測負 edge）
_RULE_FALLBACK = os.environ.get('M3_RULE_FALLBACK', 'abstain').lower()

MODEL_TYPE = 'm3_chip'
_DEFAULT_GATE = 0.40
_versions = None
_model_load_failed = False

# 面板快取：{最新交易日: DataFrame}，避免一輪投票重複計算 22 次
_panel_cache = {}


def _load_versions():
    """服役版本 + candidate 影子版本（影子只寫台帳、不影響投票）。"""
    global _versions, _model_load_failed
    if _versions is not None or _model_load_failed:
        return _versions or []
    try:
        import joblib
        import model_registry as registry
        out = []
        for ver, path, serving in registry.loadable_versions(MODEL_TYPE):
            try:
                out.append((ver, joblib.load(path), serving))
                logger.info('[model3/chip] 已載入 %s v%s（%s）', MODEL_TYPE,
                            ver['version'] if ver else '?',
                            '服役' if serving else '影子')
            except Exception as e:
                logger.warning('[model3/chip] v%s 載入失敗：%s',
                               ver['version'] if ver else '?', e)
        if not out:
            _model_load_failed = True
        _versions = out
    except Exception as e:
        _model_load_failed = True
        logger.warning('[model3/chip] RF 模型載入失敗，使用規則 fallback：%s', e)
    return _versions or []


def _load_model():
    """Lazy-load 對外服務的 RF bundle（維持舊呼叫慣例）。"""
    vs = _load_versions()
    return vs[0][1] if vs else None


# 訊號在台帳裡以數值表示，方便統一計算方向準確率
_SIGNAL_VALUE = {'Buy': 1.0, 'Hold': 0.0, 'Sell': -1.0}


def _decide(bundle, last):
    """把 bundle 的部署政策套到一列特徵上，回傳 (signal, proba, raw_signal)。"""
    feature_cols = bundle.get('feature_cols')
    gate = float(bundle.get('proba_gate', _DEFAULT_GATE))
    sell_policy = bundle.get('sell_policy', 'allow')
    proba = bundle['model'].predict_proba(last[feature_cols].values)[0]
    cls = int(proba.argmax())
    top_p = float(proba[cls])
    raw_signal = bundle['label_map'][cls]
    if top_p < gate:
        return 'Hold', proba, raw_signal
    if raw_signal == 'Sell' and sell_policy == 'suppress':
        return 'Hold', proba, raw_signal
    return raw_signal, proba, raw_signal


def _log_all(panel, stock_id, last):
    """
    記下各版本對這檔股票的訊號。

    Hold 在台帳裡是 0，評估時視為**棄權**不計入方向準確率——
    否則一個永遠 Hold 的模型會拿到「沒有錯過」的假象。
    賣出側已被 sell_policy 抑制（走查顯示無 edge），這裡照實記錄它實際送出的訊號。
    """
    try:
        import model_registry as registry
        as_of = last['trade_date'].iloc[0]
        h = registry.MODEL_TYPES[MODEL_TYPE]['horizon_days']
        close = last['close'].iloc[0] if 'close' in last.columns else None
        for ver, bundle, _serving in _load_versions():
            if ver is None:
                continue
            try:
                signal, _proba, _raw = _decide(bundle, last)
            except Exception:
                continue
            registry.log_predictions(MODEL_TYPE, [{
                'stock_id': stock_id,
                'predicted_on': as_of,
                'target_date': registry.estimate_target_date(as_of, h),
                'horizon_days': h,
                'ref_value': float(close) if close is not None else None,
                'predicted_value': _SIGNAL_VALUE.get(signal, 0.0),
                'baseline_value': None,   # 方向側的基準以多數類別現算，見 model_lifecycle
            }], version_id=ver['id'])
    except Exception as e:
        logger.warning('[model3/chip] 台帳寫入略過：%s', e)


def _build_panel_cached():
    """
    撈追蹤股票近期資料，建含橫斷面特徵的面板。

    快取鍵用「最新交易日」的便宜查詢——原本是先跑完整查詢再檢查快取，
    一輪投票 24 檔就會重複查 24 次（見 panel_cache 的說明）。
    """
    import panel_cache

    def build():
        import pandas as pd
        from m3_features import build_panel

        with get_conn() as conn:
            raw = pd.read_sql("""
                SELECT c.stock_id, c.trade_date,
                       c.foreign_investor_buy AS foreign_net,
                       c.investment_trust_buy AS trust_net,
                       c.dealer_buy           AS dealer_net,
                       c.total_net_buy        AS total_net,
                       p.volume, p.close_price AS close
                FROM stock_chip_analysis c
                JOIN stock_daily_prices p USING (stock_id, trade_date)
                JOIN stock_info s ON s.stock_id = c.stock_id AND s.is_tracking = true
                WHERE c.trade_date >= (
                    SELECT max(trade_date) - INTERVAL '150 days' FROM stock_daily_prices
                )
                ORDER BY c.stock_id, c.trade_date
            """, conn)
        if raw.empty:
            return None
        panel = build_panel(raw)
        logger.info('[model3/chip] 面板重建：%d 筆 / %d 檔',
                    len(panel), panel['stock_id'].nunique())
        return panel

    return panel_cache.cached('m3_chip', build)


def _rf_signal(stock_id: str) -> dict | None:
    """以 RF 模型推論；資料不足或任何失敗回傳 None（呼叫端 fallback 至規則）。"""
    bundle = _load_model()
    if bundle is None:
        return None
    try:
        feature_cols = bundle.get('feature_cols')
        gate = float(bundle.get('proba_gate', _DEFAULT_GATE))
        sell_policy = bundle.get('sell_policy', 'allow')

        panel = _build_panel_cached()
        if panel is None or panel.empty:
            return None
        rows = panel[panel['stock_id'] == stock_id]
        if rows.empty:
            return None
        last = rows.iloc[[-1]]

        proba = bundle['model'].predict_proba(last[feature_cols].values)[0]
        cls = int(proba.argmax())
        label_map = bundle['label_map']
        top_p = float(proba[cls])
        raw_signal = label_map[cls]

        if top_p < gate:
            signal, conf = 'Hold', round(top_p, 3)
            reason = (f'RF 籌碼模型信心不足（Buy {proba[2]:.0%} / Hold {proba[1]:.0%} / '
                      f'Sell {proba[0]:.0%}，門檻 {gate:.0%}），觀望')
        elif raw_signal == 'Sell' and sell_policy == 'suppress':
            signal, conf = 'Hold', round(top_p, 3)
            reason = (f'RF 籌碼模型傾向 Sell（機率 {top_p:.0%}），但走查顯示賣出訊號'
                      f'方向準確率僅約 52%、平均報酬為負，故不採用，改為觀望')
        else:
            signal, conf = raw_signal, round(top_p, 3)
            reason = (f'RF 籌碼模型判定 {signal}（機率 {top_p:.0%}；'
                      f'近5日買超天數={int(last.iloc[0]["buy_days_5"])}，'
                      f'外資5日淨額/均量={last.iloc[0]["foreign_5d"]:+.2f}，'
                      f'同儕外資買超百分位={last.iloc[0]["cs_foreign_5d"]:.0%}）')

        logger.info('[model3/chip] %s → %s (RF proba=%.2f, raw=%s)',
                    stock_id, signal, top_p, raw_signal)
        _log_all(panel, stock_id, last)
        return {
            'stock_id': stock_id, 'signal': signal, 'confidence': conf,
            'reason': reason, 'data_days': int(len(rows)), 'engine': 'rf',
        }
    except Exception as e:
        logger.warning('[model3/chip] RF 推論失敗 %s，fallback 規則：%s', stock_id, e)
        return None


def get_signal(stock_id: str, days: int = 5) -> dict:
    rf = _rf_signal(stock_id)
    if rf is not None:
        return rf

    if _RULE_FALLBACK == 'allow':
        logger.info('[model3/chip] %s RF 不可用，依設定使用規則引擎', stock_id)
        return _rule_signal(stock_id, days)

    logger.info('[model3/chip] %s RF 不可用（多為缺價格資料），棄權', stock_id)
    return {
        'stock_id': stock_id, 'signal': 'Hold', 'confidence': 0.0,
        'reason': ('籌碼模型無法推論此股（通常是缺少價格資料或歷史不足）。'
                   '規則引擎經實測方向準確率僅 48%（低於隨機），故不採用，本模型棄權'),
        'data_days': 0, 'engine': 'abstain',
    }


def _rule_signal(stock_id: str, days: int = 5) -> dict:
    """
    分析最近 N 天籌碼資料。
    Returns: { stock_id, signal, confidence, reason, data_days }
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT trade_date, foreign_investor_buy, investment_trust_buy,
                       dealer_buy, total_net_buy, foreign_holding_ratio
                FROM stock_chip_analysis
                WHERE stock_id = %s
                ORDER BY trade_date DESC
                LIMIT %s
            """, (stock_id, days))
            rows = cur.fetchall()

    if not rows:
        return {
            'stock_id': stock_id, 'signal': 'Hold', 'confidence': 0.0,
            'reason': '無籌碼資料', 'data_days': 0,
        }

    cols = ['trade_date','foreign_investor_buy','investment_trust_buy',
            'dealer_buy','total_net_buy','foreign_holding_ratio']
    data = [dict(zip(cols, r)) for r in rows]
    n = len(data)

    # 連續買超天數
    buy_streak  = sum(1 for d in data if (d['total_net_buy'] or 0) > 0)
    sell_streak = sum(1 for d in data if (d['total_net_buy'] or 0) < 0)

    # 外資方向（最重要）
    foreign_sum = sum((d['foreign_investor_buy'] or 0) for d in data)

    # 投信方向
    trust_sum = sum((d['investment_trust_buy'] or 0) for d in data)

    if buy_streak >= 3 and foreign_sum > 0:
        signal, confidence = 'Buy', min(0.5 + buy_streak * 0.1, 0.95)
        reason = f'法人連續 {buy_streak} 日買超，外資合計 {foreign_sum:+,} 張'
    elif sell_streak >= 3 and foreign_sum < 0:
        signal, confidence = 'Sell', min(0.5 + sell_streak * 0.1, 0.95)
        reason = f'法人連續 {sell_streak} 日賣超，外資合計 {foreign_sum:+,} 張'
    elif foreign_sum > 0:
        signal, confidence = 'Buy', 0.45
        reason = f'外資小幅買超 {foreign_sum:+,} 張，方向偏多但不明確'
    elif foreign_sum < 0:
        signal, confidence = 'Sell', 0.45
        reason = f'外資小幅賣超 {foreign_sum:+,} 張，方向偏空但不明確'
    else:
        signal, confidence = 'Hold', 0.3
        reason = f'法人方向不明，{n} 日合計買賣超接近零'

    logger.info('[model3/chip] %s → %s (buy_streak=%d, foreign=%+d)', stock_id, signal, buy_streak, foreign_sum)
    return {
        'stock_id': stock_id, 'signal': signal, 'confidence': round(confidence, 3),
        'reason': reason, 'data_days': n,
    }
