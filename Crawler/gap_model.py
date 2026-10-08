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

**線上推論的時序（2026-09-29 修正，見 AI/Doc/ModelAccuracy.md 第二節）**：
訓練面板每列的 night_* 是「該列 trade_date 當天早上 05:00 收的夜盤」，描述的是
那一天的開盤。推論取每檔「最新收盤日 D」那列時，它的 night_* 是 D 的夜盤——
早已發生的跳空。要預測 D+1 的開盤，必須換成 **D+1 的夜盤**（D 15:00 ~ D+1 05:00），
那一場 05:00 才收完；所以跳空預測只在 06:10 外生資料更新後才成立
（`scheduler.job_gap_predict`，06:20）。夜盤還沒收完就不預測、也不寫台帳——
8/7 ~ 9/22 的 230 筆線上紀錄就是這樣寫錯的（預測值與**當天已發生**的跳空相關 0.76、
與目標日 −0.03），已全部標記 `invalid_reason`。

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


def _fresh_night_row(latest_tw):
    """
    取「最新收盤日之後」那一場夜盤（也就是次一交易日早上 05:00 收的那列）。

    回傳 (Series|None, date|None)。None 代表那一場還沒收完（或還沒抓進資料庫），
    此時最新一列的 night_* 描述的是已發生的開盤，不能拿來預測明天。
    """
    import pandas as pd
    from night_features import load_night_panel
    night = load_night_panel('TX')
    if night.empty:
        return None, None
    night['trade_date'] = pd.to_datetime(night['trade_date'])
    later = night[night['trade_date'] > pd.Timestamp(latest_tw)]
    if later.empty:
        return None, None
    if len(later) > 1:
        # 夜盤已經走到兩個交易日之後，代表個股行情落後了：這時「最新一列」的自身特徵
        # 是兩天前的，硬配最新夜盤只會得到另一種對齊錯誤。等 17:30 新鮮度補齊後再說。
        logger.warning('[gap] 個股行情停在 %s，夜盤已到 %s：行情落後，不預測',
                       str(latest_tw)[:10], str(later['trade_date'].max())[:10])
        return None, None
    row = later.iloc[0]          # 最新收盤日之後的那一場夜盤 = 次一交易日的開盤定價
    return row, row['trade_date'].date()


def _build_latest_features():
    """
    為每檔股票建立「最新一列」的特徵，用於預測次一交易日的開盤跳空。

    回傳 (DataFrame, 使用的美股日期, 台股最新收盤日, 夜盤日期)。
    夜盤日期為 None 代表次一交易日的夜盤尚未收完，回傳的特徵**不能**拿來預測。
    """
    import pandas as pd
    from train_gap import load_dataset
    from night_features import NIGHT_FEATURES

    df = load_dataset()
    if df.empty:
        return None, None, None, None

    latest_tw = df['trade_date'].max()

    # 取每檔最新一列。注意：這一列的 gap 欄位是「今日已發生的跳空」，
    # 特徵中的美股與夜盤資料也都是今日開盤前的。要預測「明日」跳空，
    # 美股要換成**最新一筆**收盤，夜盤要換成**次一交易日那一場**。
    latest = df[df['trade_date'] == latest_tw].copy()

    from us_features import build_us_daily, LOAD_US_SQL
    from db.connection import get_conn
    with get_conn() as conn:
        raw_us = pd.read_sql(LOAD_US_SQL, conn)
    us = build_us_daily(raw_us).sort_values('us_date')
    newest_us = us.iloc[-1]

    night_row, night_date = _fresh_night_row(latest_tw)
    key = f'{latest_tw}|{night_date}'
    if key in _cache:
        return _cache[key]

    for col in us.columns:
        if col != 'us_date' and col in latest.columns:
            latest[col] = newest_us[col]
    latest['us_gap_days'] = (pd.Timestamp(newest_us['us_date']) - latest_tw).days
    latest['us_gap_days'] = latest['us_gap_days'].clip(lower=0)

    if night_row is not None:
        for col in NIGHT_FEATURES:
            if col in latest.columns:
                latest[col] = night_row[col]

    result = (latest, newest_us['us_date'], latest_tw, night_date)
    _cache.clear()
    _cache[key] = result
    logger.info('[gap] 特徵建立：台股最新 %s，採用美股 %s 收盤，夜盤 %s',
                str(latest_tw)[:10], str(newest_us['us_date'])[:10],
                night_date or '尚未收完（不預測）')
    return result


def _log_all(versions, usable, tw_date, night_date=None):
    """
    寫入台帳。天真基準取 0（明天平盤開出）——這是跳空唯一誠實的天真基準：
    「不知道就猜不跳空」。方向側的基準則在評估時以多數類別現算
    （見 model_lifecycle 的說明），不在這裡寫死。
    """
    try:
        import model_registry as registry
        # 目標日就是夜盤那一場所定價的開盤日；沒有夜盤日期時退回行事曆推估
        target_date = night_date or registry.estimate_target_date(tw_date, 1)
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
        'night_date': 採用的夜盤日期（= 被預測的開盤日）,
        'predictions': [{stock_id, gap_pct, direction, ...}],
    }

    次一交易日的夜盤（15:00 ~ 翌日 05:00）還沒收完時回 available=False、
    `night_pending=True`：那時手上只有「今天的夜盤」，算出來的是今天已發生的跳空，
    輸出它、寫進台帳都是錯的（2026-09-20 報告第二節）。
    """
    versions = _load_versions()
    if not versions:
        return {'available': False,
                'reason': '跳空模型尚未訓練（請執行 UnifiedModel/train_gap.py）'}
    bundle = versions[0][1]
    try:
        latest, us_date, tw_date, night_date = _build_latest_features()
        if latest is None or latest.empty:
            return {'available': False, 'reason': '無足夠資料建立特徵'}
        if night_date is None:
            return {'available': False, 'night_pending': True,
                    'tw_last_date': str(tw_date)[:10],
                    'reason': (f'{str(tw_date)[:10]} 之後的台指期夜盤尚未收完或尚未入庫'
                               '（夜盤 05:00 收、06:10 外生資料更新後才有次日跳空預測）')}

        cols = bundle['feature_cols']
        usable = latest[latest[cols].notna().all(axis=1)]
        if usable.empty:
            return {'available': False, 'reason': '特徵有缺失，無法預測'}
        if stock_ids:
            usable = usable[usable['stock_id'].isin(stock_ids)]
            if usable.empty:
                return {'available': False, 'reason': '指定股票無可用特徵'}

        preds = bundle['model'].predict(usable[cols].values)
        _log_all(versions, usable, tw_date, night_date)
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
            'night_date': str(night_date)[:10],
            'model_note': ('走查驗證：相關 0.6935、方向準確率 72.24%、MAE 0.69%'
                           '（Iteration 28 加入台指期夜盤，加入前為 0.6727／69.92%）；'
                           f'採用 {str(night_date)[:10]} 早上收的夜盤，預測的是該日開盤；'
                           '此為盤前參考資訊，跳空於開盤瞬間發生，事後無法交易'),
            'predictions': out,
        }
    except Exception as e:
        logger.warning('[gap] 預測失敗：%s', e)
        return {'available': False, 'reason': f'預測失敗：{str(e)[:100]}'}
