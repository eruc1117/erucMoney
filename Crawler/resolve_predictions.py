"""
預測台帳回填（Iteration 21）
────────────────────────────
把 `model_predictions` 中已到期的預測填上實際值。這是「模型到底準不準」
唯一可信的資料來源——訓練時的走查指標再漂亮，也不等於線上表現。

## 一切都在 adj_close 的尺度上比較

Iteration 18 的教訓：`close_price` 含除權息與減資造成的機械性缺口，
旺宏 2017-08-28 原始資料是單日 +123.56%。用它算實際報酬會把公司行動
誤判成模型預測失準（或誤判成大賺）。

因此本模組**一律以 `adj_close` 計算**，高低價則以 `adj_close ÷ close_price`
求出當日還原係數再套用（與 `train_range.py` 的目標定義一致）。

對 `close`（LSTM 逐日收盤預測）而言，這帶來一個必要的轉換：
模型預測的是**未還原的收盤價**，而還原後的實際價與它不在同一尺度。
故實際值改以「基準日價格尺度」表示：

    actual = ref_value × adj_close(目標日) ÷ adj_close(基準日)

如此 predicted 與 actual 直接可比，且除權息不會被算成預測誤差。

## 交易日以真實日曆為準

寫入台帳時 target_date 只能用行事曆推估（未來交易日還沒進資料庫）。
回填時改以「基準日之後第 N 個**交易日**」定位，並把 target_date 修正為真值。

用法：
    python resolve_predictions.py            # 回填所有已到期預測
    python resolve_predictions.py --dry-run
"""

import argparse
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

PENDING_SQL = """
SELECT p.id, p.stock_id, p.target_kind, p.predicted_on, p.horizon_days,
       p.ref_value, p.predicted_value
  FROM model_predictions p
 WHERE p.actual_value IS NULL
 ORDER BY p.stock_id, p.predicted_on
"""

PRICE_SQL = """
SELECT stock_id, trade_date, open_price, high_price, low_price,
       close_price, adj_close, volume
  FROM stock_daily_prices
 WHERE stock_id = ANY(%s) AND close_price > 0
 ORDER BY stock_id, trade_date
"""

# 美股模型（Iteration 32）的實際值在另一張表。用 target_kind 判斷要查哪張，
# 不用 stock_id 的長相猜——'TSM' 與 '2330' 剛好長得不一樣，但那是巧合不是規則。
US_PRICE_SQL = """
SELECT ticker, trade_date, open_price, high_price, low_price,
       close_price, adj_close, volume
  FROM us_daily_prices
 WHERE ticker = ANY(%s) AND close_price > 0
 ORDER BY ticker, trade_date
"""

US_KINDS = {'us_gap', 'us_close'}

# 成交量的 20 日均量視窗，與 train_volume.py 的 rolling(20, min_periods=10) 同口徑。
# 量不套還原係數：訓練端用的是 panel 的原始 volume，這裡跟著它走。
VOL20_WINDOW = 20
VOL20_MIN = 10


def _load_prices(stock_ids, us: bool = False):
    """
    回傳 {stock_id: {'dates': [...], 'idx': {date: i},
                     'adj': [...], 'adj_high': [...], 'adj_low': [...],
                     'adj_open': [...], 'vol': [...]}}

    價格全部已套用 adj_close ÷ close_price 的還原係數；`vol` 是原始成交量。
    `us=True` 時改讀 `us_daily_prices`——兩張表的欄位語意相同，只有來源不同。
    """
    from db.connection import get_conn
    out = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(US_PRICE_SQL if us else PRICE_SQL, (list(stock_ids),))
            rows = cur.fetchall()

    grouped = defaultdict(list)
    for sid, d, o, h, lo, c, adj, vol in rows:
        grouped[sid].append((d, o, h, lo, c, adj, vol))

    for sid, recs in grouped.items():
        dates, adjs, ah, al, ao, vols = [], [], [], [], [], []
        for d, o, h, lo, c, adj, vol in recs:
            c = float(c)
            adj = float(adj) if adj is not None else c
            f = adj / c if c else 1.0          # 當日還原係數
            dates.append(d)
            adjs.append(adj)
            ah.append(float(h) * f if h is not None else None)
            al.append(float(lo) * f if lo is not None else None)
            ao.append(float(o) * f if o is not None else None)
            vols.append(float(vol) if vol is not None else None)
        out[sid] = {
            'dates': dates, 'idx': {d: i for i, d in enumerate(dates)},
            'adj': adjs, 'adj_high': ah, 'adj_low': al, 'adj_open': ao,
            'vol': vols,
        }
    return out


def _resolve_one(kind, px, base_i, h, ref_value):
    """
    回傳 (actual_value, true_target_date) 或 None（資料尚未齊全）。

    各 target_kind 的定義刻意與訓練時的目標定義對齊，
    否則「線上準確率」與「走查準確率」比的是兩件事。
    """
    n = len(px['dates'])
    tgt_i = base_i + h
    if tgt_i >= n:
        return None                                  # 尚未到期

    adj_base = px['adj'][base_i]
    if not adj_base:
        return None
    tgt_date = px['dates'][tgt_i]

    if kind in ('close', 'us_close'):
        # 以基準日價格尺度表示的還原後實際收盤（台股與美股同一個公式）
        base_ref = float(ref_value) if ref_value is not None else adj_base
        return base_ref * px['adj'][tgt_i] / adj_base, tgt_date

    if kind in ('gap', 'us_gap'):
        # 次一交易日開盤相對前一交易日收盤的跳空比例（台股與美股同一個公式）
        op = px['adj_open'][tgt_i]
        if op is None:
            return None
        prev_adj = px['adj'][tgt_i - 1]
        if not prev_adj:
            return None
        return op / prev_adj - 1, tgt_date

    if kind == 'range':
        # 未來 h 個交易日（不含基準日）的最高減最低，除以基準日收盤
        win_h = [v for v in px['adj_high'][base_i + 1: tgt_i + 1] if v is not None]
        win_l = [v for v in px['adj_low'][base_i + 1: tgt_i + 1] if v is not None]
        if len(win_h) < h or len(win_l) < h:
            return None
        return (max(win_h) - min(win_l)) / adj_base, tgt_date

    if kind == 'volatility':
        # 未來 h 個交易日的日報酬標準差（未年化，與 train_volatility.py 同口徑）
        seq = px['adj'][base_i: tgt_i + 1]
        rets = [seq[i] / seq[i - 1] - 1 for i in range(1, len(seq)) if seq[i - 1]]
        if len(rets) < h:
            return None
        m = sum(rets) / len(rets)
        var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1) if len(rets) > 1 else 0.0
        return var ** 0.5, tgt_date

    if kind == 'signal':
        # 訊號的實際結果＝持有 h 個交易日的報酬率
        return px['adj'][tgt_i] / adj_base - 1, tgt_date

    if kind == 'volume':
        # 未來 h 個交易日的平均量 ÷ 基準日的 20 日均量
        #（與 train_volume.py 的 y_volume 同口徑；量不套還原係數）
        fut = [v for v in px['vol'][base_i + 1: tgt_i + 1] if v is not None]
        if len(fut) < h:
            return None
        win = [v for v in px['vol'][max(base_i - VOL20_WINDOW + 1, 0): base_i + 1]
               if v is not None]
        if len(win) < VOL20_MIN:
            return None
        vol20 = sum(win) / len(win)
        if not vol20:
            return None
        return (sum(fut) / len(fut)) / vol20, tgt_date

    logger.warning('[resolve] 未知 target_kind：%s', kind)
    return None


def resolve(dry_run: bool = False) -> dict:
    from db.connection import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(PENDING_SQL)
            pending = cur.fetchall()

    if not pending:
        return {'pending': 0, 'resolved': 0, 'still_open': 0}

    # 台股與美股分開取價：同一批 pending 裡兩種都有，靠 target_kind 分流
    tw_ids = sorted({r[1] for r in pending if r[2] not in US_KINDS})
    us_ids = sorted({r[1] for r in pending if r[2] in US_KINDS})
    prices = _load_prices(tw_ids) if tw_ids else {}
    us_prices = _load_prices(us_ids, us=True) if us_ids else {}

    updates, still_open, no_data = [], 0, 0
    for pid, sid, kind, pred_on, h, ref_value, _pv in pending:
        px = (us_prices if kind in US_KINDS else prices).get(sid)
        if px is None:
            no_data += 1
            continue
        base_i = px['idx'].get(pred_on)
        if base_i is None:
            # 基準日不是交易日（例如以週末日期記錄）→ 取其前一個交易日
            earlier = [i for i, d in enumerate(px['dates']) if d <= pred_on]
            if not earlier:
                no_data += 1
                continue
            base_i = earlier[-1]
        got = _resolve_one(kind, px, base_i, int(h or 1), ref_value)
        if got is None:
            still_open += 1
            continue
        actual, tgt_date = got
        updates.append((float(actual), tgt_date, pid))

    if updates and not dry_run:
        from psycopg2.extras import execute_batch
        with get_conn() as conn:
            with conn.cursor() as cur:
                execute_batch(cur, """
                    UPDATE model_predictions
                       SET actual_value = %s, target_date = %s,
                           resolved_at = CURRENT_TIMESTAMP
                     WHERE id = %s
                """, updates, page_size=500)
            conn.commit()

    return {'pending': len(pending), 'resolved': len(updates),
            'still_open': still_open, 'no_price_data': no_data,
            'dry_run': dry_run}


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(levelname)s] %(message)s')
    ap = argparse.ArgumentParser(description='回填模型預測的實際值')
    ap.add_argument('--dry-run', action='store_true', help='只計算不寫入')
    args = ap.parse_args()

    res = resolve(dry_run=args.dry_run)
    print(f"待回填 {res['pending']} 筆 → 已回填 {res['resolved']} 筆"
          f"（尚未到期 {res['still_open']}、無價格資料 {res.get('no_price_data', 0)}）"
          + ('　[dry-run，未寫入]' if res.get('dry_run') else ''))
