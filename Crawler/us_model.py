"""
美股開盤跳空推論（Iteration 32）
────────────────────────────────
把 `UnifiedModel/train_us_gap.py` 的模型接上線：回答「今晚美股大概開在哪」。

## 時序：它預測的是還沒開盤的那一場

台北 21:30（夏令）＝ 紐約 09:30 開盤。在那之前，台股日盤（13:30 收）、
韓日（14:30 收）都已經結束——本模組就是拿這些亞洲盤資訊去預測美股開盤跳空。
所以合理的呼叫時間是台灣時間下午到晚上，排程排在 20:00。

面板的最後一列對應**已經開過**的那一場，直接拿來預測等於回顧；
`us_panel.build(forward=True)` 會補上「下一場」那一列，本模組只用那一列。

## 界線：這不是買賣訊號

跳空在開盤瞬間發生，事後買不到——與台股跳空模型（Iteration 16）相同。
而 `explore_us.py` 量到「開盤之後」那一段（D 收 ÷ D 開）相關僅 0.02、
方向 49.4%，**低於多數類別 51.45%**：能預測的部分不可交易，可交易的部分不能預測。
本模組不進投票計分，只做盤前參考。

## 各標的的準確度差很多（Iteration 34 起 23 檔）

走查分標的（`results/us_gap_model.md`）：ASX 相關 0.476、TSM 0.453、UMC 0.408，
AAPL 0.16、MSFT 0.15 墊底（EWT 0.566 最高，但它本身就是台股，不算數）。
台灣資訊是這個模型的訊號來源，所以與台股連動越深的標的越準——
這個排序本身就是「訊號是真的」的旁證。Iteration 34 據此以巢狀走查重新檢討清單：
11 檔候選全數過門檻加入，原 12 檔沒有一檔退場（AAPL/MSFT 邊際但仍過門檻）。
每筆預測都附上該標的的走查成績，前端要顯示出來。
"""

import logging
import os
import sys

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_UNIFIED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            '..', 'UnifiedModel')
if _UNIFIED_DIR not in sys.path:
    sys.path.insert(0, _UNIFIED_DIR)

MODEL_TYPE = 'us_gap'
HORIZON = 1

_versions = None
_load_failed = False


def _load_versions():
    """服役版 + candidate 影子版（影子只寫台帳、不對外輸出）。"""
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
                logger.info('[us_gap] 已載入 v%s（%s）',
                            ver['version'] if ver else '?', '服役' if serving else '影子')
            except Exception as e:
                logger.warning('[us_gap] v%s 載入失敗：%s',
                               ver['version'] if ver else '?', e)
        if not out:
            _load_failed = True
        _versions = out
    except Exception as e:
        _load_failed = True
        logger.warning('[us_gap] 模型載入失敗：%s', e)
    return _versions or []


def _build_forward():
    """
    下一場美股的特徵列（每檔一列）。回傳 (DataFrame, 基準美股日, 亞洲盤日)。

    基準日刻意取**最後一場已收盤的美股交易日**而不是 forward 列的日期：
    台帳的 `predicted_on` 要是一個真實存在的交易日，回填才找得到它，
    再往後數 1 個交易日就是被預測的那一場（`resolve_predictions` 用真實日曆修正）。
    """
    def build():
        import us_panel
        import train_us_gap
        panel = us_panel.build(blocks=train_us_gap.BLOCKS, forward=True)
        if panel.empty:
            return None
        fwd = panel[panel['is_forward']].reset_index(drop=True)
        base_date = panel[~panel['is_forward']]['trade_date'].max()
        # 用到的是哪一天的台股盤——連假或盤前呼叫時會落後一天，要讓使用者看得到
        tw_date = None
        if 'tw_stale_days' in fwd.columns and not fwd.empty:
            stale = fwd['tw_stale_days'].dropna()
            if not stale.empty:
                tw_date = (fwd['trade_date'].iloc[0]
                           - pd.Timedelta(days=int(stale.iloc[0])))
        return {'rows': fwd, 'base_date': base_date, 'tw_date': tw_date}

    try:
        import panel_cache
        return panel_cache.cached('us_gap', build)
    except Exception:
        return build()


def _log_all(versions, rows, base_date):
    """
    寫入台帳。天真基準取 0（平盤開出）——與台股跳空模型同一個基準，
    也是跳空唯一誠實的天真基準：「不知道就猜不跳」。
    方向側的基準（多數類別）由評估端現算，不寫死在這裡。
    """
    try:
        import model_registry as registry
        target_date = registry.estimate_target_date(base_date, HORIZON)
        for ver, bundle, _serving in versions:
            if ver is None:
                continue
            cols = bundle['feature_cols']
            if not set(cols).issubset(rows.columns):
                continue
            usable = rows[rows[cols].notna().all(axis=1)]
            if usable.empty:
                continue
            vals = bundle['model'].predict(usable[cols].values)
            registry.log_predictions(MODEL_TYPE, [{
                'stock_id': tk,
                'predicted_on': base_date,
                'target_date': target_date,
                'horizon_days': HORIZON,
                'ref_value': float(close),
                'predicted_value': float(v),
                'baseline_value': 0.0,
            } for tk, close, v in zip(usable['ticker'], usable['prev_close'], vals)],
                version_id=ver['id'])
    except Exception as e:
        logger.warning('[us_gap] 台帳寫入略過：%s', e)


def predict_gaps(tickers: list = None) -> dict:
    """
    預測下一場美股各標的的開盤跳空。

    Returns {available, base_date, predictions: [{ticker, gap_pct, direction,
             last_close, implied_open, walk_forward: {...}}], ...}
    """
    versions = _load_versions()
    if not versions:
        return {'available': False,
                'reason': '美股跳空模型尚未訓練（請執行 UnifiedModel/train_us_gap.py）'}
    ver, bundle, _ = versions[0]
    try:
        built = _build_forward()
        if not built or built['rows'].empty:
            return {'available': False, 'reason': '無足夠資料建立特徵'}
        rows, base_date = built['rows'], built['base_date']

        cols = bundle['feature_cols']
        missing = [c for c in cols if c not in rows.columns]
        if missing:
            # 靜默退化的唯一出口（risk_model 曾因此無聲退回 EWMA）：說出來
            logger.warning('[us_gap] 缺少 %d 個特徵欄：%s', len(missing), missing[:5])
            return {'available': False, 'reason': f'特徵欄不符：{missing[:5]}'}

        _log_all(versions, rows, base_date)

        usable = rows[rows[cols].notna().all(axis=1)]
        if usable.empty:
            return {'available': False, 'reason': '特徵有缺失，無法預測'}
        if tickers:
            want = {str(t).strip().upper() for t in tickers}
            usable = usable[usable['ticker'].isin(want)]
            if usable.empty:
                return {'available': False, 'reason': '指定標的無可用特徵'}

        preds = bundle['model'].predict(usable[cols].values)
        q = bundle.get('quantiles', {})
        big_up, big_dn = float(q.get('0.95', 0.02)), float(q.get('0.05', -0.02))
        per_ticker = bundle.get('per_ticker', {})

        out = []
        for tk, close, v in zip(usable['ticker'], usable['prev_close'], preds):
            gap = float(v)
            wf = per_ticker.get(tk, {})
            out.append({
                'ticker': tk,
                'gap_pct': round(gap * 100, 3),
                'direction': '開高' if gap > 0.001 else ('開低' if gap < -0.001 else '平盤'),
                # 幅度預測的 MAE 幾乎沒有贏過「猜 0」，所以只標「是否偏大」，
                # 不讓使用者把 gap_pct 當成可下單的數字
                'magnitude': ('偏大' if gap > big_up or gap < big_dn else '一般'),
                'last_close': float(close) if close and np.isfinite(close) else None,
                'implied_open': (round(float(close) * (1 + gap), 2)
                                 if close and np.isfinite(close) else None),
                'walk_forward': ({'corr': round(wf['corr'], 3),
                                  'dir_acc': round(wf['dir_acc'] * 100, 2),
                                  'dir_base': round(wf['dir_base'] * 100, 2)}
                                 if wf else None),
            })
        out.sort(key=lambda r: -r['gap_pct'])

        wfm = bundle.get('walk_forward', {})
        return {
            'available': True,
            'base_date': str(base_date)[:10],
            'target_session': str(usable['trade_date'].max())[:10],
            'tw_session': str(built['tw_date'])[:10] if built.get('tw_date') else None,
            'version': ver['version'] if ver else None,
            'model_note': (
                f"走查：相關 {wfm.get('corr', 0):.4f}、方向 {wfm.get('dir_acc', 0)*100:.2f}%"
                f"（多數類別 {wfm.get('dir_base', 0)*100:.2f}%）。"
                '訊號來自台股與韓日當日盤——美股自身歷史單獨使用時相關僅 0.0085。'
                '跳空於開盤瞬間發生，此為盤前參考，不是買賣訊號'),
            'predictions': out,
        }
    except Exception as e:
        logger.warning('[us_gap] 預測失敗：%s', e)
        return {'available': False, 'reason': f'預測失敗：{str(e)[:120]}'}


def market_snapshot(days: int = 60) -> dict:
    """
    美股最新報價與近期走勢（前端總覽用）。與模型無關，資料庫直出。
    """
    from db.connection import get_conn
    sql = """
        WITH latest AS (
            SELECT ticker, MAX(trade_date) AS d FROM us_daily_prices GROUP BY ticker
        )
        SELECT p.ticker, t.name, t.category, p.trade_date, p.close_price, p.open_price,
               p.volume,
               (SELECT close_price FROM us_daily_prices q
                 WHERE q.ticker = p.ticker AND q.trade_date < p.trade_date
                 ORDER BY q.trade_date DESC LIMIT 1) AS prev_close,
               (SELECT close_price FROM us_daily_prices q
                 WHERE q.ticker = p.ticker AND q.trade_date <= p.trade_date - %s
                 ORDER BY q.trade_date DESC LIMIT 1) AS old_close
          FROM us_daily_prices p
          JOIN latest l ON l.ticker = p.ticker AND l.d = p.trade_date
          LEFT JOIN us_tickers t ON t.ticker = p.ticker
         ORDER BY p.ticker
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (days,))
                rows = cur.fetchall()
    except Exception as e:
        logger.warning('[us_gap] 快照查詢失敗：%s', e)
        return {'available': False, 'reason': str(e)[:160]}

    items = []
    for tk, name, cat, d, close, op, vol, prev, old in rows:
        close = float(close)
        items.append({
            'ticker': tk, 'name': name, 'category': cat,
            'trade_date': str(d), 'close': close,
            'change_pct': round((close / float(prev) - 1) * 100, 2) if prev else None,
            'period_pct': round((close / float(old) - 1) * 100, 2) if old else None,
            'volume': int(vol or 0),
        })
    items.sort(key=lambda r: -(r['change_pct'] if r['change_pct'] is not None else -99))
    return {'available': True, 'period_days': days, 'items': items,
            'as_of': max((i['trade_date'] for i in items), default=None)}


def reset_cache():
    global _versions, _load_failed
    _versions, _load_failed = None, False
