"""
新聞訊號模型的推論端（Iteration 47）
──────────────────────────────────
三個模型共用一份推論面板（price + news + event，`train_news_models.load_data(for_inference=True)`），
每檔取最新一列：

    news_event_vol   次日振幅（量級）        → range_pct、對自身 20 日中位數的倍數、對同儕的分位
    news_drift       營收公布後 20 日方向    → signal +1／−1／0（|預測| 未達門檻就棄權），只在漂移窗口內
    news_tone        有新聞日的 3 日方向     → 同上，只在今天有新聞時

## 服役規則

三個版本都登錄、都寫台帳（影子），但**只有訓練關卡通過的（bundle['gates']['deploy']）才對外輸出**。
未通過的在 `signals()` 裡以 `serving=False` 帶出關卡數字，前端照實顯示「未通過，僅累積線上紀錄」——
這是方案文件五道關卡的落地：沒過關的模型不是不存在，是不能拿來做決策。

## 台帳

`_log_all` 對每檔、每個可載入版本寫一列：
    range  類：predicted_value = 預測振幅比例，baseline_value = 20 日振幅中位數（持續性基準）
    signal 類：predicted_value = +1／−1／0，baseline_value = 0（不知道就不出手）
棄權（0）在 model_lifecycle 不計入方向準確率，與 M3 一致；這樣才數得出出手率。
"""

import logging

import numpy as np

logger = logging.getLogger(__name__)

MODEL_KEYS = ['news_event_vol', 'news_drift', 'news_tone']

_versions = {}          # model_type → [(version_row|None, bundle, is_serving), ...]
_load_failed = set()


def _load_versions(model_type: str) -> list:
    if model_type in _versions or model_type in _load_failed:
        return _versions.get(model_type, [])
    try:
        import joblib
        import model_registry as registry
        out = []
        for ver, path, serving in registry.loadable_versions(model_type):
            try:
                out.append((ver, joblib.load(path), serving))
            except Exception as e:
                logger.warning('[news_models] %s v%s 載入失敗：%s', model_type,
                               ver['version'] if ver else '?', e)
        if not out:
            _load_failed.add(model_type)
        _versions[model_type] = out
    except Exception as e:
        _load_failed.add(model_type)
        logger.warning('[news_models] %s 載入失敗：%s', model_type, e)
    return _versions.get(model_type, [])


def reset_cache():
    _versions.clear()
    _load_failed.clear()


def _panel():
    """推論面板：每檔全部歷史（滾動特徵要），取用時再挑最新一列。"""
    def build():
        import os
        import sys
        um = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'UnifiedModel')
        if um not in sys.path:
            sys.path.insert(0, um)
        import train_news_models as T
        d = T.load_data(for_inference=True)
        return d if not d.empty else None
    try:
        import panel_cache
        return panel_cache.cached('news_signals', build)
    except Exception:
        return build()


def gates_summary() -> dict:
    """訓練報告的關卡數字（results/news_models.json）；沒有就回空。"""
    import json
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'UnifiedModel',
                        'results', 'news_models.json')
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def is_deployed(model_type: str) -> bool:
    vs = _load_versions(model_type)
    if not vs:
        return False
    return bool(vs[0][1].get('gates', {}).get('deploy'))


def credibility_of(model_type: str) -> str:
    """給模型目錄用：關卡通過 proven、沒通過 none、還沒訓練 unvalidated。"""
    vs = _load_versions(model_type)
    if not vs:
        g = gates_summary().get(model_type, {}).get('gates')
        if not g:
            return 'unvalidated'
        return 'proven' if g.get('deploy') else 'none'
    return 'proven' if vs[0][1].get('gates', {}).get('deploy') else 'none'


def _predict_rows(bundle: dict, rows):
    cols = bundle['feature_cols']
    if not set(cols).issubset(rows.columns):
        return None
    x = rows[cols].values.astype(float)
    return bundle['model'].predict(x)


def _to_signal(bundle: dict, pred: np.ndarray) -> np.ndarray:
    thr = float(bundle.get('act_threshold') or 0)
    sig = np.sign(pred)
    sig[np.abs(pred) < thr] = 0
    return sig


def _eligible(bundle: dict, rows):
    """列篩選與訓練一致：漂移窗口內／今天有新聞；其餘列棄權（signal 0）。"""
    rf = bundle.get('row_filter')
    if rf == 'in_window':
        return rows['ev_in_window'].fillna(0).values == 1
    if rf == 'has_news':
        return rows['ns_has_news'].fillna(0).values == 1
    return np.ones(len(rows), dtype=bool)


def _log_all(model_type: str, versions, rows, as_of):
    try:
        import model_registry as registry
        for ver, bundle, _serving in versions:
            if ver is None:
                continue
            pred = _predict_rows(bundle, rows)
            if pred is None:
                continue
            h = int(bundle.get('horizon') or registry.MODEL_TYPES[model_type]['horizon_days'])
            kind = bundle.get('target_kind')
            if kind == 'signal':
                sig = _to_signal(bundle, pred)
                sig[~_eligible(bundle, rows)] = 0
                vals, base = sig, np.zeros(len(sig))
            else:
                vals = pred
                bcol = bundle.get('baseline_col')
                base = rows[bcol].values if bcol and bcol in rows.columns else np.full(len(pred), np.nan)
            out = []
            for sid, close, d0, v, b in zip(rows['stock_id'], rows['close'], rows['trade_date'], vals, base):
                d0 = d0.date()
                out.append({'stock_id': str(sid), 'predicted_on': d0,
                            'target_date': registry.estimate_target_date(d0, h),
                            'horizon_days': h, 'ref_value': float(close), 'predicted_value': float(v),
                            'baseline_value': None if b is None or np.isnan(b) else float(b)})
            registry.log_predictions(model_type, out, version_id=ver['id'])
    except Exception as e:
        logger.warning('[news_models] %s 台帳寫入略過：%s', model_type, e)


def signals(stock_ids: list = None, log: bool = True) -> dict:
    """
    每檔最新一列的六個維度 + 三個模型的輸出。

    Returns {
        'available', 'as_of',
        'models': {key: {serving, credibility, gates, label, horizon_days, target_kind}},
        'results': [{stock_id, as_of, dims:{ns_*, ev_*}, event_vol:{...}|None, drift:{...}|None, tone:{...}|None}],
    }
    """
    from news_signal_features import NEWS_FEATURES, EVENT_FEATURES
    import model_registry as registry

    panel = _panel()
    if panel is None or panel.empty:
        return {'available': False, 'reason': '無足夠資料建立新聞訊號面板'}
    latest = panel.sort_values('trade_date').groupby('stock_id').tail(1).reset_index(drop=True)
    as_of = latest['trade_date'].max()
    # 各檔行情更新有先後（17:30 新鮮度補齊前會差一兩天）；落後一週以上的才不算「最新」
    import pandas as pd
    latest = latest[latest['trade_date'] >= as_of - pd.Timedelta(days=7)].reset_index(drop=True)
    if stock_ids:
        want = {str(s).strip() for s in stock_ids}
        latest = latest[latest['stock_id'].astype(str).isin(want)].reset_index(drop=True)
    if latest.empty:
        return {'available': False, 'reason': '指定股票無最新資料'}

    as_of_date = as_of.date()
    models_meta, per_model = {}, {}
    gates_json = gates_summary()
    for key in MODEL_KEYS:
        vs = _load_versions(key)
        meta = registry.MODEL_TYPES.get(key, {})
        deployed = bool(vs) and bool(vs[0][1].get('gates', {}).get('deploy'))
        models_meta[key] = {
            'label': meta.get('label', key), 'target_kind': meta.get('target_kind'),
            'horizon_days': meta.get('horizon_days'), 'serving': deployed,
            'credibility': credibility_of(key),
            'gates': (vs[0][1].get('gates') if vs else gates_json.get(key, {}).get('gates')) or {},
            'version': vs[0][0]['version'] if vs and vs[0][0] else None,
        }
        if not vs:
            continue
        if log:
            _log_all(key, vs, latest, as_of_date)
        bundle = vs[0][1]
        pred = _predict_rows(bundle, latest)
        if pred is None:
            continue
        if bundle.get('target_kind') == 'signal':
            sig = _to_signal(bundle, pred)
            elig = _eligible(bundle, latest)
            sig[~elig] = 0
            per_model[key] = [{'score': float(p), 'signal': int(s), 'eligible': bool(e),
                               'label': {1: '偏多', -1: '偏空', 0: '棄權'}[int(s)]}
                              for p, s, e in zip(pred, sig, elig)]
        else:
            base = latest[bundle['baseline_col']].values if bundle.get('baseline_col') in latest.columns else np.full(len(pred), np.nan)
            ratio = pred / np.where(base > 0, base, np.nan)
            order = pred.argsort().argsort()
            peer_pct = 100.0 * order / max(len(pred) - 1, 1)
            per_model[key] = [{'range_pct': round(float(p) * 100, 3),
                               'hist_median_pct': None if np.isnan(b) else round(float(b) * 100, 3),
                               'self_ratio': None if np.isnan(r) else round(float(r), 2),
                               'peer_pct': round(float(q), 1),
                               'is_elevated': bool((not np.isnan(r)) and r >= 1.3)}
                              for p, b, r, q in zip(pred, base, ratio, peer_pct)]

    results = []
    for i, r in latest.iterrows():
        dims = {}
        row_as_of = str(r['trade_date'])[:10]
        for c in NEWS_FEATURES + EVENT_FEATURES:
            v = r.get(c)
            dims[c] = None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)
        row = {'stock_id': str(r['stock_id']), 'as_of': row_as_of, 'close': float(r['close']),
               'dims': dims}
        for key, short in (('news_event_vol', 'event_vol'), ('news_drift', 'drift'), ('news_tone', 'tone')):
            vals = per_model.get(key)
            # 未通過關卡的模型不對外給值——只留 serving=False 與關卡數字讓人看得到它為何缺席
            row[short] = vals[i] if vals is not None and models_meta[key]['serving'] else None
            if vals is not None and not models_meta[key]['serving']:
                row[f'{short}_shadow'] = vals[i]
        results.append(row)
    results.sort(key=lambda x: x['stock_id'])
    return {'available': True, 'as_of': str(as_of_date), 'models': models_meta, 'results': results,
            'note': ('六個維度來自新聞方案：意外程度（ev_sue）、情緒（ns_sent）、新穎度（ns_novelty）、'
                     '報導強度（ns_n_articles）、異常注意力（ns_abn_attn）、不確定性（ns_uncertainty）；'
                     '只有通過訓練關卡的模型才有輸出，其餘只累積線上台帳')}


def log_daily() -> dict:
    """排程用：對全部追蹤股票寫一次台帳（不對外輸出）。"""
    res = signals(None, log=True)
    return {'available': res.get('available'), 'as_of': res.get('as_of'),
            'n': len(res.get('results', [])),
            'serving': [k for k, m in res.get('models', {}).items() if m.get('serving')]}
