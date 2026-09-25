"""
投組層級風險：相關性調整（Iteration 14）
─────────────────────────────────────────
`risk_model.py` 是**單筆**風險控管：每檔獨立算出「押多少、停損放哪」。
但它有一個 Iteration 13 就記在遺留問題裡的缺陷：

    24 檔多為台灣電子股，彼此高度相關。
    同時持有多檔時，實際投組風險遠高於各筆風險的加總假設——
    因為它們會一起漲、一起跌，分散效果比想像中小得多。

本模組把單筆部位建議調整為**投組層級**的建議：

    投組變異數 = wᵀ Σ w      （Σ 為報酬共變異數矩陣）
    分散比率   = Σᵢ wᵢσᵢ / √(wᵀΣw)
                 ＝「各自獨立時的風險加總」÷「實際投組風險」
                 值為 1 代表完全相關（毫無分散效果），越大分散效果越好

    調整係數   = 目標投組波動 ÷ 實際投組波動
    若一籃子標的高度相關，實際波動會超標，係數 < 1 → 全體按比例縮減部位。

這不是把單筆建議打折，而是修正「假設彼此獨立」這個錯誤前提。
"""

import logging
import math

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 投組整體願意承受的日波動率上限。
# 單筆 2% 風險 × 若干檔，若彼此獨立，投組波動約 √n 倍；
# 但電子股高度相關，實際會接近線性相加，故需要明確上限。
TARGET_PORTFOLIO_VOL = 0.02
CORR_LOOKBACK = 120        # 估計相關係數的回看天數（約半年）
MIN_OVERLAP = 60           # 兩檔至少要有這麼多天重疊才採用其相關係數


def _load_returns(stock_ids: list, lookback: int) -> pd.DataFrame:
    """取回近期日報酬矩陣（欄＝股票、列＝日期）。"""
    from db.connection import get_conn
    with get_conn() as conn:
        df = pd.read_sql("""
            SELECT stock_id, trade_date, close_price AS close
            FROM stock_daily_prices
            WHERE close_price > 0
              AND trade_date >= (SELECT max(trade_date) - INTERVAL '400 days'
                                 FROM stock_daily_prices)
            ORDER BY stock_id, trade_date
        """, conn)
    if df.empty:
        return pd.DataFrame()

    df = df[df['stock_id'].isin(stock_ids)]
    wide = df.pivot_table(index='trade_date', columns='stock_id',
                          values='close', aggfunc='last').sort_index()
    rets = wide.pct_change().tail(lookback)
    return rets


def correlation_report(stock_ids: list, lookback: int = CORR_LOOKBACK) -> dict:
    """回傳相關係數矩陣與摘要統計（供診斷與前端顯示）。"""
    rets = _load_returns(stock_ids, lookback)
    if rets.empty or rets.shape[1] < 2:
        return {'available': False, 'reason': '可用股票不足兩檔'}

    valid = rets.columns[rets.notna().sum() >= MIN_OVERLAP]
    rets = rets[valid]
    corr = rets.corr()

    off = corr.values[~np.eye(len(corr), dtype=bool)]
    return {
        'available': True,
        'stocks': list(corr.columns),
        'n_days': int(rets.notna().sum().min()),
        'avg_corr': float(np.nanmean(off)),
        'max_corr': float(np.nanmax(off)),
        'min_corr': float(np.nanmin(off)),
        'corr_matrix': corr.round(3).to_dict(),
    }


def adjust_positions(positions: dict, predicted_vols: dict,
                     lookback: int = CORR_LOOKBACK,
                     target_vol: float = TARGET_PORTFOLIO_VOL) -> dict:
    """
    把單筆部位建議調整為投組層級。

    positions      {stock_id: 單筆建議部位比例（0~1）}
    predicted_vols {stock_id: 預測日波動率}
    回傳 {stock_id: 調整後部位} 及診斷資訊。

    共變異數以「預測波動率 × 歷史相關係數」組成——
    波動用預測值（前瞻），相關係數用歷史值（相關性比波動穩定得多，
    且我們沒有相關係數的預測模型；這點在報告中誠實標示）。
    """
    ids = [s for s in positions if s in predicted_vols and predicted_vols[s]]
    if len(ids) < 2:
        return {'adjusted': dict(positions), 'scale': 1.0,
                'available': False, 'reason': '可用股票不足兩檔'}

    rets = _load_returns(ids, lookback)
    if rets.empty:
        return {'adjusted': dict(positions), 'scale': 1.0,
                'available': False, 'reason': '無足夠報酬資料'}

    ids = [s for s in ids if s in rets.columns and rets[s].notna().sum() >= MIN_OVERLAP]
    if len(ids) < 2:
        return {'adjusted': dict(positions), 'scale': 1.0,
                'available': False, 'reason': '重疊交易日不足'}

    corr = rets[ids].corr().values
    corr = np.nan_to_num(corr, nan=0.0)
    np.fill_diagonal(corr, 1.0)

    sigma = np.array([predicted_vols[s] for s in ids], dtype=float)
    cov = corr * np.outer(sigma, sigma)

    w = np.array([positions[s] for s in ids], dtype=float)
    w_sum = float(w.sum())
    if w_sum <= 0:
        return {'adjusted': dict(positions), 'scale': 1.0,
                'available': False, 'reason': '部位總和為零'}
    w_norm = w / w_sum          # 以相對權重計算投組風險特性

    port_var = float(w_norm @ cov @ w_norm)
    port_vol = math.sqrt(max(port_var, 1e-12))
    naive_vol = float(np.sum(w_norm * sigma))       # 完全相關時的風險
    diversification = naive_vol / port_vol if port_vol > 0 else 1.0

    # 全體按同一係數縮放，使投組日波動達到目標上限
    scale = float(min(target_vol / (port_vol * w_sum), 1.0)) if port_vol * w_sum > 0 else 1.0

    # **務必轉成原生 float**：numpy 2.x 的 repr(np.float64(5.1)) 是 'np.float64(5.1)'，
    # psycopg2 無法轉換 numpy 型別時會退回 repr 字串插入，
    # 產生 SET position_pct = np.float64(5.1) → PostgreSQL 報
    # 「schema "np" does not exist」。這個錯訊完全看不出真正原因。
    adjusted = {s: float(round(positions[s] * scale, 4)) for s in positions}
    avg_corr = float(np.mean(corr[~np.eye(len(corr), dtype=bool)]))
    return {
        'adjusted': adjusted,
        'scale': float(round(scale, 4)),
        'available': True,
        'n_stocks': int(len(ids)),
        'avg_corr': avg_corr,
        'portfolio_vol': float(round(port_vol * w_sum, 5)),
        'naive_vol': float(round(naive_vol * w_sum, 5)),
        'diversification_ratio': float(round(diversification, 3)),
        'target_vol': float(target_vol),
        'reason': (f'{len(ids)} 檔平均相關係數 {avg_corr:.2f}，'
                   f'分散比率 {diversification:.2f}；'
                   f'依單筆建議的投組日波動為 {port_vol * w_sum:.2%}，'
                   f'目標上限 {target_vol:.1%} → 全體部位乘上 {scale:.2f}'),
    }
