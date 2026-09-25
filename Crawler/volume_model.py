"""
成交量／流動性推論（Iteration 31）
─────────────────────────────────
把 `UnifiedModel/train_volume.py` 訓練出來的模型接上線，輸出兩個東西：

    vol_multiple   預測未來 5 日均量 ÷ 目前 20 日均量
    liquidity      以訓練期分位換算的等級：thin / normal / thick

## 為什麼要有這個

`cash_allocator` 原本只用價格與振幅算部位，沒問過「這檔吃不吃得下這筆錢」。
量能萎縮時同樣的單量衝擊成本會放大，而且出場更難。

## 這不是方向訊號

輸出與漲跌無關，**不進投票的方向計分**。它只做兩件事：
縮小預測量能萎縮者的部位、以及在量能過薄時直接排除。
把它當第四個買賣訊號就會重蹈 Iteration 10 的覆轍。

## 與 risk_model 一樣的靜默退化風險

特徵欄位對不上時本模組會回 `engine='none'` 並讓所有股票落在 normal，
線上看起來完全正常。改完 `train_volume.py` 後務必檢查 `engine` 欄位。
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MODEL_TYPE = 'volume'
HORIZON = 5

_versions = None
_load_failed = False


def _load_versions():
    """服役版 + candidate 影子版（影子只寫台帳、不影響輸出）。"""
    global _versions, _load_failed
    if _versions is not None or _load_failed:
        return _versions or []
    try:
        import joblib
        import model_registry as registry
        out = []
        for ver, path, serving in registry.loadable_versions(MODEL_TYPE):
            try:
                b = joblib.load(path)
                out.append((ver, b, serving))
                logger.info('[volume] 已載入 v%s（%s，%d 個特徵）',
                            ver['version'] if ver else '?',
                            '服役' if serving else '影子', len(b.get('feature_cols', [])))
            except Exception as e:
                logger.warning('[volume] v%s 載入失敗：%s',
                               ver['version'] if ver else '?', e)
        if not out:
            _load_failed = True
        _versions = out
    except Exception as e:
        _load_failed = True
        logger.warning('[volume] 模型載入失敗：%s', e)
    return _versions or []


def _build_panel() -> pd.DataFrame:
    """
    最新一日的特徵面板。

    與訓練端共用 `UnifiedModel/panel.py`——這正是統一資料層存在的理由：
    Iteration 30 之前訓練與推論各自組特徵，`risk_model` 就曾因欄位對不上
    靜默退回 EWMA。

    快取放在查詢之後會完全失效（Iteration 22 的 23 秒）——用 panel_cache。
    """
    def build():
        import os
        import sys
        um = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'UnifiedModel')
        if um not in sys.path:
            sys.path.insert(0, um)
        import train_volume
        d, cols = train_volume.load_data(for_inference=True)
        if d.empty:
            return d
        latest = d.sort_values('trade_date').groupby('stock_id').tail(1)
        return latest.reset_index(drop=True)

    import panel_cache
    return panel_cache.cached('volume', build)


def _log_all(versions, panel, as_of):
    """
    寫入台帳。天真基準取 `base_volume`（近 5 日均量 ÷ 20 日均量，即「量能持續」）
    ——與 `train_volume.py` 走查時要打敗的對象同一個，否則線上與走查比的
    不是同一件事。

    刻意記整個面板，不是呼叫端指定的那幾檔：台帳要回答的是「這個模型
    今天輸出了什麼」，被查詢的股票子集只是呼叫端的事。

    影子版（candidate）也要寫——`loadable_versions` 的說明講得很清楚，
    candidate 累積不到線上紀錄就永遠無法達標凍結。
    """
    try:
        import model_registry as registry

        target_date = registry.estimate_target_date(as_of, HORIZON)
        for ver, bundle, _serving in versions:
            if ver is None:
                continue
            cols = bundle['feature_cols']
            if not set(cols).issubset(panel.columns):
                continue
            p = bundle['model'].predict(panel[cols].values)
            vals = np.exp(p) if bundle.get('log_target') else p
            rows = []
            for (_i, r), v in zip(panel.iterrows(), vals):
                base = r.get('base_volume')
                ref = r.get('vol20')
                rows.append({
                    'stock_id': r['stock_id'],
                    'predicted_on': as_of,
                    'target_date': target_date,
                    'horizon_days': HORIZON,
                    'ref_value': float(ref) if ref is not None and np.isfinite(ref) else None,
                    'predicted_value': float(v),
                    'baseline_value': (float(base) if base is not None
                                       and np.isfinite(base) else None),
                })
            registry.log_predictions(MODEL_TYPE, rows, version_id=ver['id'])
    except Exception as e:
        logger.warning('[volume] 台帳寫入略過：%s', e)


def get_liquidity(stock_ids=None) -> dict:
    """
    回傳 {stock_id: {...}}。無模型或無資料時回空 dict，呼叫端須自行處理。
    """
    versions = _load_versions()
    if not versions:
        return {'engine': 'none', 'results': {}}

    try:
        panel = _build_panel()
    except Exception as e:
        logger.warning('[volume] 面板建立失敗：%s', e)
        return {'engine': 'none', 'results': {}}
    if panel is None or panel.empty:
        return {'engine': 'none', 'results': {}}

    full = panel                       # 台帳寫整個面板，不受呼叫端的股票子集影響
    if stock_ids:
        want = {str(s).strip() for s in stock_ids}
        panel = panel[panel['stock_id'].isin(want)]
    if panel.empty:
        return {'engine': 'none', 'results': {}}

    ver, bundle, _serving = versions[0]
    cols = bundle['feature_cols']
    missing = [c for c in cols if c not in panel.columns]
    if missing:
        # 靜默退化的唯一出口：說出來，不要假裝正常
        logger.warning('[volume] 缺少 %d 個特徵欄，模型不可用：%s', len(missing), missing[:5])
        return {'engine': 'none', 'results': {}, 'missing_features': missing[:5]}

    _log_all(versions, full, full['trade_date'].max())

    X = panel[cols].values
    pred = np.exp(bundle['model'].predict(X)) if bundle.get('log_target') \
        else bundle['model'].predict(X)

    q = bundle.get('quantiles', {})
    thin_cut = float(q.get('0.25', 0.8))
    thick_cut = float(q.get('0.75', 1.2))

    out = {}
    for sid, mult, vol20, date in zip(panel['stock_id'], pred,
                                      panel.get('vol20', pd.Series(np.nan, index=panel.index)),
                                      panel['trade_date']):
        m = float(mult)
        level = 'thin' if m < thin_cut else 'thick' if m > thick_cut else 'normal'
        est_vol = float(vol20) * m if np.isfinite(vol20) else None
        out[str(sid)] = {
            'stock_id': str(sid),
            'as_of': str(date)[:10],
            'vol_multiple': round(m, 3),
            'liquidity': level,
            'avg_volume_20d': int(vol20) if np.isfinite(vol20) else None,
            # 預測未來 5 日的日均量（張）。部位大小要跟這個比，不是跟現在的量比
            'expected_daily_volume': int(est_vol) if est_vol else None,
            'note': ('預測量能萎縮，衝擊成本與出場難度上升' if level == 'thin'
                     else '預測量能放大' if level == 'thick' else '量能接近常態'),
        }

    return {'engine': f'model v{ver["version"]}' if ver else 'model',
            'horizon_days': HORIZON, 'results': out}


def reset_cache():
    global _versions, _load_failed
    _versions, _load_failed = None, False
