"""
開盤跳空預測（盤前參考資訊）
────────────────────────────
回答「今晚美股這樣走，明天台股大概開在哪」。

**定位：參考資訊，不是買賣訊號。** 跳空發生在開盤那一刻，事後無法交易；
它的用途是盤前心理準備，以及讓風險模組把預期跳空納入停損距離。

為何這件事做得到而「預測漲跌」做不到（Iteration 15 實測）：
    美股隔夜 → 台股開盤跳空   相關 +0.66（費半 ETF 可解釋約 44% 變異）
    美股隔夜 → 台股盤中報酬   相關 −0.13
資訊在開盤瞬間被完全吸收——這正是它對收盤到收盤預測無用、
卻能高精度預測跳空本身的原因。

**Iteration 28 加入台指期夜盤**。夜盤（15:00~翌日 05:00）是市場在台股開盤前
對次日的直接定價，比美股這個間接代理更貼近目標。同批樣本走查：

    自身 + 美股（原版）    相關 0.6727、方向 69.92%
    自身 + 夜盤            相關 0.6851、方向 71.61%   ← 不用美股就已勝出
    自身 + 美股 + 夜盤     相關 0.6935、方向 72.24%   ← 部署版本
    夜盤單因子 night_ret   相關 0.5430、方向 69.92%   ← 一個特徵打平原版整個模型

注意夜盤的時序：`futures_daily` 的 after_market 那列領先**同一個 trade_date**
的開盤（中位數差 0.185%），故用同日對齊；當日 position（日盤）的欄位一概不能碰。

走查驗證表現（`UnifiedModel/results/gap_model.md`、`gap_ablation.md`）：
    相關 0.6935、R² 0.481、MAE 0.688%、方向準確率 72.24%
    對照最強單因子基準（費半線性迴歸）：0.484 / 0.228 / 0.857% / 66.8%
"""

import logging
import os
import sys
from datetime import date

logger = logging.getLogger(__name__)

_UNIFIED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            '..', 'UnifiedModel')
if _UNIFIED_DIR not in sys.path:
    sys.path.insert(0, _UNIFIED_DIR)

MODEL_TYPE = 'gap'

_versions = None          # [(version_row|None, bundle, is_serving), ...]
_load_failed = False
_cache = {}


def _load_versions():
    """服役版本 + candidate 影子版本（影子只寫台帳、不對外輸出）。"""
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
                logger.info('[gap] 已載入 %s v%s（%s）', MODEL_TYPE,
                            ver['version'] if ver else '?',
                            '服役' if serving else '影子')
            except Exception as e:
                logger.warning('[gap] v%s 載入失敗：%s',
                               ver['version'] if ver else '?', e)
        if not out:
            _load_failed = True
        _versions = out
    except Exception as e:
        _load_failed = True
        logger.warning('[gap] 跳空模型載入失敗：%s', e)
    return _versions or []


def _load():
    vs = _load_versions()
    return vs[0][1] if vs else None


def _build_latest_features():
    """
    為每檔股票建立「最新一列」的特徵，用於預測次一交易日的開盤跳空。

    回傳 (DataFrame, 使用的美股日期, 台股最新收盤日)。
    """
    import pandas as pd
    from train_gap import load_dataset

    df = load_dataset()
    if df.empty:
        return None, None, None

    latest_tw = df['trade_date'].max()
    key = str(latest_tw)
    if key in _cache:
        return _cache[key]

    # 取每檔最新一列。注意：這一列的 gap 欄位是「今日已發生的跳空」，
    # 而特徵中的美股資料是今日開盤前的隔夜走勢。
    # 要預測「明日」跳空，必須把美股特徵換成**最新一筆**美股收盤。
    latest = df[df['trade_date'] == latest_tw].copy()

    from us_features import build_us_daily, LOAD_US_SQL
    from db.connection import get_conn
    with get_conn() as conn:
        raw_us = pd.read_sql(LOAD_US_SQL, conn)
    us = build_us_daily(raw_us).sort_values('us_date')
    newest_us = us.iloc[-1]

    for col in us.columns:
        if col != 'us_date' and col in latest.columns:
            latest[col] = newest_us[col]
    latest['us_gap_days'] = (pd.Timestamp(newest_us['us_date']) - latest_tw).days
    latest['us_gap_days'] = latest['us_gap_days'].clip(lower=0)

    result = (latest, newest_us['us_date'], latest_tw)
    _cache.clear()
    _cache[key] = result
    logger.info('[gap] 特徵建立：台股最新 %s，採用美股 %s 收盤',
                str(latest_tw)[:10], str(newest_us['us_date'])[:10])
    return result


def _log_all(versions, usable, tw_date):
    """
    寫入台帳。天真基準取 0（明天平盤開出）——這是跳空唯一誠實的天真基準：
    「不知道就猜不跳空」。方向側的基準則在評估時以多數類別現算
    （見 model_lifecycle 的說明），不在這裡寫死。
    """
    try:
        import model_registry as registry
        target_date = registry.estimate_target_date(tw_date, 1)
        for ver, bundle, _serving in versions:
            if ver is None:
                continue
            cols = bundle['feature_cols']
            if not set(cols).issubset(usable.columns):
                continue
            vals = bundle['model'].predict(usable[cols].values)
            rows = [{
                'stock_id': sid,
                'predicted_on': tw_date,
                'target_date': target_date,
                'horizon_days': 1,
                'ref_value': float(close),
                'predicted_value': float(v),
                'baseline_value': 0.0,
            } for sid, close, v in zip(usable['stock_id'], usable['close'], vals)]
            registry.log_predictions(MODEL_TYPE, rows, version_id=ver['id'])
    except Exception as e:
        logger.warning('[gap] 台帳寫入略過：%s', e)


def predict_gaps(stock_ids: list = None) -> dict:
    """
    預測各股票次一交易日的開盤跳空。

    Returns {
        'available': bool,
        'us_date': 採用的美股收盤日,
        'tw_last_date': 台股最新收盤日,
        'predictions': [{stock_id, gap_pct, direction, ...}],
    }
    """
    versions = _load_versions()
    if not versions:
        return {'available': False,
                'reason': '跳空模型尚未訓練（請執行 UnifiedModel/train_gap.py）'}
    bundle = versions[0][1]
    try:
        latest, us_date, tw_date = _build_latest_features()
        if latest is None or latest.empty:
            return {'available': False, 'reason': '無足夠資料建立特徵'}

        cols = bundle['feature_cols']
        usable = latest[latest[cols].notna().all(axis=1)]
        if usable.empty:
            return {'available': False, 'reason': '特徵有缺失，無法預測'}
        if stock_ids:
            usable = usable[usable['stock_id'].isin(stock_ids)]
            if usable.empty:
                return {'available': False, 'reason': '指定股票無可用特徵'}

        preds = bundle['model'].predict(usable[cols].values)
        _log_all(versions, usable, tw_date)
        out = []
        for sid, close, gp in zip(usable['stock_id'], usable['close'], preds):
            gap = float(gp)
            out.append({
                'stock_id': sid,
                'gap_pct': round(gap * 100, 3),
                'direction': '開高' if gap > 0.001 else ('開低' if gap < -0.001 else '平盤'),
                'last_close': float(close),
                'implied_open': round(float(close) * (1 + gap), 2),
            })
        out.sort(key=lambda r: -r['gap_pct'])

        return {
            'available': True,
            'us_date': str(us_date)[:10],
            'tw_last_date': str(tw_date)[:10],
            'model_note': ('走查驗證：相關 0.6935、方向準確率 72.24%、MAE 0.69%'
                           '（Iteration 28 加入台指期夜盤，加入前為 0.6727／69.92%）；'
                           '此為盤前參考資訊，跳空於開盤瞬間發生，事後無法交易'),
            'predictions': out,
        }
    except Exception as e:
        logger.warning('[gap] 預測失敗：%s', e)
        return {'available': False, 'reason': f'預測失敗：{str(e)[:100]}'}
