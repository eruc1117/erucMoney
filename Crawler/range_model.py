"""
週振幅預測（波段選股用）
────────────────────────
回答「接下來一週，哪些股票的高低點差距會特別大」。

為何這件事做得到：本專案反覆驗證方向預測沒有 edge（超越基準 −0.09%），
但**振幅／波動率有實質預測力**。振幅預測正是後者的應用。

走查驗證（`UnifiedModel/results/range_model.md`）：
    排序相關 0.664、R² 0.363、MAE 2.50%
    **lift 1.989**——預測振幅前 10% 的股票，實際振幅是全體平均的近兩倍
    對照最強基準（ATR 外推）：排序相關 0.639、lift 1.898

## 「顯著差異」怎麼判定

單看預測振幅會被「這檔本來就波動大」誤導，故同時看兩個維度：

    相對自身  預測振幅 ÷ 該股歷史振幅中位數     → 排除長期高波動股
    相對同儕  當日全體股票中的百分位排名        → 排除全市場都在震盪的日子

**兩者同時偏高**才標記為顯著（`is_significant`）。

用途：波段操作選股、風險預警、與買賣訊號搭配（同樣訊號優先選振幅大的）。
注意：**振幅大不代表會漲**——方向仍是不可預測的，這裡只回答「會不會震」。
"""

import logging
import os
import sys

logger = logging.getLogger(__name__)

_UNIFIED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            '..', 'UnifiedModel')
if _UNIFIED_DIR not in sys.path:
    sys.path.insert(0, _UNIFIED_DIR)

MODEL_TYPE = 'range'

# 顯著判定門檻
SELF_RATIO_TH = 1.15      # 預測振幅須達自身歷史中位數的 1.15 倍
PEER_PCT_TH = 0.70        # 且在同儕中排名前 30%

_versions = None          # [(version_row|None, bundle, is_serving), ...]
_load_failed = False
_cache = {}


def _load_versions():
    """
    載入「對外服務的版本」與（若不同）candidate 影子版本。

    影子版本的預測只寫台帳、不對外輸出——沒有它，candidate 永遠累積不到
    線上紀錄，自動凍結機制在第一次凍結後就會卡死（見 model_registry 的說明）。
    """
    global _versions, _load_failed
    if _versions is not None or _load_failed:
        return _versions or []
    try:
        import joblib
        import model_registry as registry
        out = []
        for ver, path, serving in registry.loadable_versions(MODEL_TYPE):
            try:
                out.append((ver, joblib.load(path), serving))
                logger.info('[range] 已載入 %s v%s（%s）', MODEL_TYPE,
                            ver['version'] if ver else '?',
                            '服役' if serving else '影子')
            except Exception as e:
                logger.warning('[range] v%s 載入失敗：%s',
                               ver['version'] if ver else '?', e)
        if not out:
            _load_failed = True
        _versions = out
    except Exception as e:
        _load_failed = True
        logger.warning('[range] 振幅模型載入失敗：%s', e)
    return _versions or []


def _load():
    """對外服務的 bundle（維持舊呼叫慣例）。"""
    vs = _load_versions()
    return vs[0][1] if vs else None


def _build_panel():
    """
    建立最新一日的特徵面板。

    快取鍵用「最新交易日」的便宜查詢，不要先把全部歷史載進來再檢查快取
    （見 panel_cache 的說明）。

    for_inference=True：不剔除目標值缺失的列，
    否則預測基準日會落後最新資料 5 個交易日（目標需要未來 5 天）。
    """
    import panel_cache

    def build():
        from train_range import load_data
        d = load_data(for_inference=True)
        return None if d.empty else d

    return panel_cache.cached('range', build)


def _log_all(versions, latest, as_of, horizon):
    """
    把各版本對「同一批股票、同一個基準日」的預測寫進台帳。

    天真基準用 `hist_range_median`（該股過去 60 日振幅中位數）——
    它就是 train_range.py 走查裡最強的簡單基準之一，且推論當下就有值。
    基準必須與預測**同時**寫下，事後才無從挑一個對自己有利的基準。
    """
    try:
        import numpy as np
        import pandas as pd
        import model_registry as registry

        target_date = registry.estimate_target_date(as_of, horizon)
        for ver, bundle, _serving in versions:
            if ver is None:
                continue
            cols = bundle['feature_cols']
            if not set(cols).issubset(latest.columns):
                continue
            p = bundle['model'].predict(latest[cols].values)
            vals = np.exp(p) if bundle.get('log_target') else p
            rows = []
            for (_i, r), v in zip(latest.iterrows(), vals):
                base = r.get('hist_range_median')
                rows.append({
                    'stock_id': r['stock_id'],
                    'predicted_on': as_of,
                    'target_date': target_date,
                    'horizon_days': horizon,
                    'ref_value': float(r['close']),
                    'predicted_value': float(v),
                    'baseline_value': (float(base) if base is not None
                                       and pd.notna(base) else None),
                })
            registry.log_predictions(MODEL_TYPE, rows, version_id=ver['id'])
    except Exception as e:
        logger.warning('[range] 台帳寫入略過：%s', e)


def predict_ranges(stock_ids: list = None) -> dict:
    """
    預測各股票未來 5 個交易日的振幅，並標記「顯著偏大」者。

    Returns {
        'available', 'as_of', 'horizon_days',
        'results': [{stock_id, range_pct, self_ratio, peer_pct,
                     is_significant, expected_high, expected_low, ...}]
    }
    """
    versions = _load_versions()
    if not versions:
        return {'available': False,
                'reason': '振幅模型尚未訓練（請執行 UnifiedModel/train_range.py）'}
    bundle = versions[0][1]
    try:
        import numpy as np
        import pandas as pd

        d = _build_panel()
        if d is None or d.empty:
            return {'available': False, 'reason': '無足夠資料建立特徵'}

        cols = bundle['feature_cols']
        # 取「特徵齊全的最後一個日期」作為預測基準日
        usable = d[d[cols].notna().all(axis=1)]
        if usable.empty:
            return {'available': False, 'reason': '特徵有缺失，無法預測'}
        as_of = usable['trade_date'].max()
        latest = usable[usable['trade_date'] == as_of].copy()

        pred_log = bundle['model'].predict(latest[cols].values)
        latest['pred_range'] = np.exp(pred_log) if bundle.get('log_target') else pred_log

        # 每一版都留下台帳（含影子版本），供日後與實際振幅比對
        _log_all(versions, latest, as_of, bundle.get('horizon', 5))

        # 相對自身：與該股歷史振幅中位數比較
        latest['self_ratio'] = (latest['pred_range'] /
                                latest['hist_range_median'].replace(0, np.nan))
        # 相對同儕：當日百分位
        latest['peer_pct'] = latest['pred_range'].rank(pct=True)

        latest['is_significant'] = (
            (latest['self_ratio'] >= SELF_RATIO_TH) &
            (latest['peer_pct'] >= PEER_PCT_TH)
        )

        if stock_ids:
            latest = latest[latest['stock_id'].isin(stock_ids)]
            if latest.empty:
                return {'available': False, 'reason': '指定股票無可用特徵'}

        out = []
        for _, r in latest.sort_values('pred_range', ascending=False).iterrows():
            close = float(r['close'])
            half = float(r['pred_range']) / 2
            out.append({
                'stock_id': r['stock_id'],
                'close': close,
                'range_pct': round(float(r['pred_range']) * 100, 2),
                'hist_median_pct': (round(float(r['hist_range_median']) * 100, 2)
                                    if pd.notna(r['hist_range_median']) else None),
                'self_ratio': (round(float(r['self_ratio']), 2)
                               if pd.notna(r['self_ratio']) else None),
                'peer_pct': round(float(r['peer_pct']) * 100, 1),
                'is_significant': bool(r['is_significant']),
                # 以預測振幅為寬度、現價為中心的粗略區間（不含方向判斷）
                'expected_high': round(close * (1 + half), 2),
                'expected_low': round(close * (1 - half), 2),
            })

        n_sig = sum(1 for r in out if r['is_significant'])
        return {
            'available': True,
            'as_of': str(as_of)[:10],
            'horizon_days': bundle.get('horizon', 5),
            'n_significant': n_sig,
            'criteria': (f'預測振幅 ≥ 自身歷史中位數 {SELF_RATIO_TH} 倍，'
                         f'且同儕排名前 {(1 - PEER_PCT_TH) * 100:.0f}%'),
            'model_note': ('走查驗證：排序相關 0.664、lift 1.989'
                           '（預測前 10% 的實際振幅為全體平均的近兩倍）。'
                           '**振幅大不代表會漲**——方向仍不可預測，此處只回答會不會震'),
            'results': out,
        }
    except Exception as e:
        logger.warning('[range] 預測失敗：%s', e)
        return {'available': False, 'reason': f'預測失敗：{str(e)[:120]}'}
