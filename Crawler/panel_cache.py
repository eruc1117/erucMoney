"""
特徵面板快取（Iteration 26）
────────────────────────────
三個推論模組（波動率、振幅、籌碼）原本都寫成這個樣子：

    raw = pd.read_sql(LOAD_SQL, conn)      # 載入全部歷史，16 萬筆
    key = str(raw['trade_date'].max())
    if key in _cache:                      # ← 檢查在昂貴查詢**之後**
        return _cache[key]

快取確實有作用——它省下了特徵計算，但**沒省下那次全表查詢**。
於是「一次算 24 檔」的功能（投票、閒置資金配置）會把整份歷史載入 24 次。
實測閒置資金配置因此要 23 秒，而且每次都一樣慢，不是冷啟動。

解法是先用一個便宜的查詢問「最新交易日是哪天」當快取鍵，
命中就直接回傳，完全不碰大查詢。

    最新交易日查詢：單一 max()，走索引，毫秒級
    全表載入：16 萬筆 × 12 欄

快取鍵用最新交易日而不是時間戳，是因為資料一天只更新一次——
同一天內重複呼叫本來就該拿到同一份面板。
"""

import logging

logger = logging.getLogger(__name__)

_caches = {}      # {名稱: (交易日, 面板)}


def latest_trade_date() -> str | None:
    """最新交易日（快取鍵）。查不到回 None，呼叫端就照常重建。"""
    try:
        from db.connection import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT max(trade_date) FROM stock_daily_prices')
                row = cur.fetchone()
        return str(row[0]) if row and row[0] else None
    except Exception as e:
        logger.warning('[panel] 取得最新交易日失敗：%s', e)
        return None


def cached(name: str, builder):
    """
    以最新交易日為鍵取用面板；未命中才呼叫 builder() 重建。

    builder 只有在真的需要時才會被呼叫——這正是重點，
    昂貴的查詢與特徵計算都應該在它裡面。
    """
    key = latest_trade_date()
    if key is not None:
        hit = _caches.get(name)
        if hit and hit[0] == key:
            return hit[1]

    panel = builder()
    if key is not None and panel is not None:
        _caches[name] = (key, panel)
    return panel


def invalidate(name: str = None) -> None:
    """資料更新後清掉快取（排程回補完可呼叫）。"""
    if name:
        _caches.pop(name, None)
    else:
        _caches.clear()
