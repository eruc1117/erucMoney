"""
風險模組（M4）：波動率預測 → 部位大小與停損距離
─────────────────────────────────────────────────
這不是第四個「買賣訊號」模型。M1/M2/M3 回答「買還是賣」，
本模組回答「**該押多少、停損放哪**」——兩者正交，不進投票計分。

為何是波動率而非方向（Iteration 12 實測，同一套走查驗證）：
    方向     準確率 51.49%，基準 51.59% → 超越基準 −0.09%（無預測力）
    波動率   相關係數 0.606、R²(log) 0.483（對照 M1 價格變動預測僅 0.05）
波動叢聚（大波動後傾向續大）是金融實證中最穩固的規律之一，
且因為波動率無法像方向那樣直接下注，套利壓力小，訊號得以留存。

模型（`UnifiedModel/train_volatility.py` 訓練）：
    天期 20 日、多尺度波動與 Parkinson 高低價估計量、log 目標，
    並與 EWMA(λ=0.94) 取平均——ML 模型排序能力強但有均值回歸傾向會低估
    突發高波動，EWMA 反應快；平均後在相關係數、R²(log)、QLIKE 三項
    **全面優於 EWMA 基準**。

輸出：
    predicted_vol   未來 20 日的預測日波動率
    vol_regime      低／中／高（依訓練集分位數）
    stop_pct        建議停損距離（%）
    position_pct    建議部位比例（%，固定風險法）
"""

import logging
import math
import os
import sys

logger = logging.getLogger(__name__)

_UNIFIED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            '..', 'UnifiedModel')
if _UNIFIED_DIR not in sys.path:
    sys.path.insert(0, _UNIFIED_DIR)

MODEL_TYPE = 'volatility'

# ── 部位與停損參數 ──────────────────────────────────────────────────────────
RISK_PER_TRADE = 0.02      # 單筆交易願意承受的資金損失比例（2%）
STOP_SIGMA = 2.0           # 停損放在幾倍波動之外（2σ ≈ 涵蓋 95% 常態波動）
HOLDING_DAYS = 5           # 預設持有天數，用於把日波動換算成持有期波動
POSITION_MIN, POSITION_MAX = 0.05, 1.00   # 部位比例上下限

_versions = None
_load_failed = False
_panel_cache = {}


def _load_versions():
    """服役版本 + candidate 影子版本（影子只寫台帳、不影響部位建議）。"""
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
                logger.info('[risk] 已載入 %s v%s（%s，blend=%s）', MODEL_TYPE,
                            ver['version'] if ver else '?',
                            '服役' if serving else '影子', b.get('blend'))
            except Exception as e:
                logger.warning('[risk] v%s 載入失敗：%s',
                               ver['version'] if ver else '?', e)
        if not out:
            _load_failed = True
        _versions = out
    except Exception as e:
        _load_failed = True
        logger.warning('[risk] 波動率模型載入失敗，改用 EWMA：%s', e)
    return _versions or []


def _load():
    vs = _load_versions()
    return vs[0][1] if vs else None


def _blended_vol(bundle, last, ewma):
    """以 bundle 的 blend 設定算出實際採用的波動率；無法計算則回 None。"""
    cols = bundle.get('feature_cols') or []
    if not all(c in last.columns for c in cols):
        return None
    if not last[cols].notna().all(axis=1).iloc[0]:
        return None
    raw_pred = float(bundle['model'].predict(last[cols].values)[0])
    model_vol = math.exp(raw_pred) if bundle.get('log_target') else raw_pred
    model_vol = max(model_vol, 1e-6)
    blend = bundle.get('blend', 'none')
    # 必須與訓練時的組合方式一致，否則線上與驗證口徑不同
    vol = (0.5 * model_vol + 0.5 * ewma if blend == 'avg'
           else max(model_vol, ewma) if blend == 'max'
           else model_vol)
    return vol, blend


def _log_all(last, ewma, stock_id):
    """
    記下各版本對這檔股票的波動率預測。

    天真基準是 EWMA(λ=0.94)——train_volatility.py 的部署門檻本來就是
    「QLIKE 須優於 EWMA」，線上評估沿用同一個對手才有可比性。
    """
    try:
        import model_registry as registry
        as_of = last['trade_date'].iloc[0]
        for ver, bundle, _serving in _load_versions():
            if ver is None:
                continue
            got = _blended_vol(bundle, last, ewma)
            if got is None:
                continue
            vol, _blend = got
            h = int(bundle.get('horizon', 20))
            registry.log_predictions(MODEL_TYPE, [{
                'stock_id': stock_id,
                'predicted_on': as_of,
                'target_date': registry.estimate_target_date(as_of, h),
                'horizon_days': h,
                'ref_value': None,
                'predicted_value': float(vol),
                'baseline_value': float(ewma),
            }], version_id=ver['id'])
    except Exception as e:
        logger.warning('[risk] 台帳寫入略過：%s', e)


def _build_panel():
    """
    建立含波動率特徵的面板。

    快取鍵改用「最新交易日」的便宜查詢——原本是先載入全部歷史再檢查快取，
    等於快取只省下特徵計算、沒省下查詢，一次算 24 檔就會全表載入 24 次
    （實測讓閒置資金配置慢到 23 秒）。見 panel_cache 的說明。
    """
    import panel_cache

    def build():
        import pandas as pd
        from db.connection import get_conn
        from features import build_panel, LOAD_SQL
        from train_volatility import add_vol_features, ewma_vol
        from dividend_adj import adjusted_returns

        with get_conn() as conn:
            raw = pd.read_sql(LOAD_SQL, conn)
        if raw.empty:
            return None
        panel = add_vol_features(build_panel(raw))
        panel = panel.sort_values(['stock_id', 'trade_date']).reset_index(drop=True)
        # 必須與訓練端同樣做除權息調整，否則線上與驗證口徑不一致
        daily = pd.Series(adjusted_returns(panel).values, index=panel.index)
        panel['ewma_vol'] = daily.groupby(panel['stock_id']).transform(ewma_vol)

        # 夜盤特徵（Iteration 30 巢狀走查 3/3 折一致選中）。
        # 推論端若不加，bundle 的 feature_cols 會找不到欄位，
        # get_risk 會靜靜地退回 EWMA——不會報錯，只是模型形同沒部署。
        from night_features import attach as attach_night
        panel = attach_night(panel, 'TX')

        logger.info('[risk] 波動率面板重建：%d 筆 / %d 檔',
                    len(panel), panel['stock_id'].nunique())
        return panel

    return panel_cache.cached('risk', build)


def _regime(vol: float, quantiles: dict) -> str:
    if not quantiles:
        return '未知'
    if vol <= quantiles.get('0.25', 0):
        return '低'
    if vol >= quantiles.get('0.75', 1e9):
        return '高'
    return '中'


def get_risk(stock_id: str, holding_days: int = HOLDING_DAYS) -> dict:
    """
    回傳該股票的風險評估與部位建議。

    停損距離 = STOP_SIGMA × 日波動率 × √持有天數
    部位比例 = 單筆風險上限 ÷ 停損距離   （固定風險法：
               不論標的波動大小，每筆交易的預期虧損金額一致）
    """
    fallback = {
        'stock_id': stock_id, 'predicted_vol': None, 'vol_regime': '未知',
        'stop_pct': None, 'position_pct': None, 'engine': 'unavailable',
        'reason': '無法取得波動率預測（資料不足或模型未訓練）',
    }
    try:
        panel = _build_panel()
        if panel is None or panel.empty:
            return fallback
        rows = panel[panel['stock_id'] == stock_id]
        if rows.empty:
            return fallback
        last = rows.iloc[[-1]]

        bundle = _load()
        ewma = float(last['ewma_vol'].iloc[0])
        engine = 'ewma'
        vol = ewma

        if bundle is not None:
            got = _blended_vol(bundle, last, ewma)
            if got is not None:
                vol, blend = got
                engine = f'model+{blend}' if blend != 'none' else 'model'
                _log_all(last, ewma, stock_id)

        if not (vol > 0) or math.isnan(vol):
            return fallback

        stop_pct = STOP_SIGMA * vol * math.sqrt(max(holding_days, 1))
        position_pct = min(max(RISK_PER_TRADE / stop_pct, POSITION_MIN), POSITION_MAX)
        regime = _regime(vol, (bundle or {}).get('vol_quantiles', {}))

        return {
            'stock_id': stock_id,
            'predicted_vol': round(vol, 5),
            'vol_regime': regime,
            'stop_pct': round(stop_pct * 100, 2),
            'position_pct': round(position_pct * 100, 1),
            'engine': engine,
            'reason': (f'預測日波動率 {vol:.2%}（{regime}波動）；'
                       f'持有 {holding_days} 日的 {STOP_SIGMA:.0f}σ 停損距離 '
                       f'{stop_pct:.1%}；以單筆風險上限 {RISK_PER_TRADE:.0%} 換算，'
                       f'建議部位 {position_pct:.0%}'),
        }
    except Exception as e:
        logger.warning('[risk] %s 評估失敗：%s', stock_id, e)
        fallback['reason'] = f'風險評估失敗：{str(e)[:80]}'
        return fallback
