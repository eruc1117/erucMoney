"""
週交易計畫策略：以 5 個交易日為一週期，優化每日買／賣／持有（Iteration 22）
──────────────────────────────────────────────────────────────────────
需求是「一週期內每天是賣、買或持有，自我迭代驗證到極限，
目標為最小虧損風險下的最大利益」。

## 先講一件必須先講的事

每日買賣本質上是方向決策，而本專案已反覆實測方向不可預測
（Iteration 11：LSTM 等同天真基準；Iteration 12：超越基準 −0.09%）。
所以本模組**不假設它會贏**。它做的是：把策略參數化 → 走查回測 →
迭代優化到收斂 → 與基準比較 → **贏不過就據實報告不部署**。

一個誠實的「不部署」結論比一個沒有基準對照的漂亮回測有價值得多。

## 策略長什麼樣

一週的計畫由五個參數決定，產生的是一個可執行的每日動作序列：

    第 0~e-1 天   空手觀望
    第 e   天     收盤買進（e = entry_day）
    第 e+1~ 天    持有，每天檢查停損／停利
    出場          觸及停損、觸及停利、持滿 max_hold、或週五收盤強制平倉

進場條件（三個同時成立才進場）：

    籌碼機率 ≥ buy_th      M3 RF 的 Buy 機率（唯一有走查證據的方向來源）
    預測振幅 ≥ range_min   振幅太小則價差不足以覆蓋成本（Iteration 19 的模型）
    預測波動 ≤ vol_max     波動太大時同樣的錯誤代價更大（Iteration 13 的模型）

停損距離 = stop_sigma × 預測日波動率 × √持有天數（沿用風險模組的定義），
停利 = take_r × 停損距離。

**訊號一律取自該週開始前的最後一個交易日**，週中不重算——
這樣沒有任何未來資訊會洩漏進來，也符合「週一早上就能拿到整週計畫」的用途。

## 目標函數

「最小虧損風險下的最大利益」對應到 **Sortino 比率**：

    Sortino = 平均週報酬 ÷ 下檔標準差

用下檔標準差而非標準差，是因為上漲的波動不是風險——這正是需求裡
「最小虧損風險」的意思。同時要求出手率不低於門檻：
一個幾乎不交易的策略風險為零但毫無用處。

## 「迭代到極限」怎麼定義

座標下降（每輪逐一掃描每個參數的候選值、保留最佳），
**連續 2 輪目標改善小於 1e-4 即視為收斂**，並以 3 個不同起點重跑
避免停在局部最優。每一輪的目標值都會印出來，可以看到它怎麼收斂的。

## 驗證方式

擴張視窗走查：參數只在訓練期優化，分數只在**下一段未見過的期間**計算。
在訓練期上調出來的漂亮分數不算數——這是本專案從 Iteration 9 起的規矩。

用法：
    python train_weekly_policy.py                # 完整走查 + 優化 + 部署判定
    python train_weekly_policy.py --quick        # 只用近 10 年資料，較快
產出：
    saved_models/weekly_policy.joblib
    results/weekly_policy.md
"""

import argparse
import math
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'Crawler'))

MODEL_DIR = os.path.join(BASE_DIR, 'saved_models')
RESULTS_DIR = os.path.join(BASE_DIR, 'results')

# ── 參數搜尋空間 ──────────────────────────────────────────────────────────────
# 刻意保持粗糙：格點太細只是在雜訊上做曲線擬合。
PARAM_GRID = {
    'entry_day':  [0, 1, 2, 3],              # 週內第幾個交易日進場
    'buy_th':     [0.30, 0.35, 0.40, 0.45, 0.50],
    'range_min':  [0.00, 0.03, 0.05, 0.07, 0.09],
    'vol_max':    [0.015, 0.020, 0.025, 0.030, 0.99],
    'stop_sigma': [1.0, 1.5, 2.0, 2.5, 3.0],
    'take_r':     [0.5, 1.0, 1.5, 2.0, 3.0],
    'max_hold':   [1, 2, 3, 4],
}
PARAM_ORDER = list(PARAM_GRID.keys())

MIN_TRADE_RATE = 0.05     # 出手率下限：低於 5% 的策略沒有實用價值
CONVERGE_EPS = 1e-4       # 目標改善低於此值視為停止進步
CONVERGE_PATIENCE = 2     # 連續幾輪沒進步就收斂
N_RESTARTS = 3            # 隨機起點數
N_FOLDS = 5               # 走查折數
DEPLOY_MARGIN = 0.10      # 外樣本 Sortino 須高出買進持有多少才部署

LOAD_SQL = """
SELECT stock_id, trade_date, open_price, high_price, low_price,
       close_price, adj_close, volume
  FROM stock_daily_prices
 WHERE close_price > 0
 ORDER BY stock_id, trade_date
"""


# ── 資料準備 ──────────────────────────────────────────────────────────────────
def load_weekly_panel(start_date=None):
    """
    建出 (股票, 週) 為單位的面板：

      每週最多 5 個交易日的還原後 OHLC
      + 該週開始前最後一個交易日的訊號（籌碼機率、預測振幅、預測波動）

    週的切分用 ISO 週。不足 3 個交易日的週（連假）直接剔除——
    那種週的「5 日計畫」本來就不成立。
    """
    from db.connection import get_conn
    with get_conn() as conn:
        px = pd.read_sql(LOAD_SQL, conn)
    if start_date:
        px = px[px['trade_date'] >= pd.Timestamp(start_date).date()]
    px['trade_date'] = pd.to_datetime(px['trade_date'])

    # 還原公司行動（Iteration 18）：高低價也要套用當日還原係數，
    # 否則除權息日的假缺口會被當成停損觸發
    px['adj_close'] = px['adj_close'].fillna(px['close_price']).astype(float)
    factor = px['adj_close'] / px['close_price'].replace(0, np.nan)
    for src, dst in (('open_price', 'aopen'), ('high_price', 'ahigh'), ('low_price', 'alow')):
        px[dst] = px[src].astype(float) * factor
    px['aclose'] = px['adj_close']

    iso = px['trade_date'].dt.isocalendar()
    px['week_key'] = iso['year'].astype(int) * 100 + iso['week'].astype(int)
    px = px.sort_values(['stock_id', 'trade_date'])
    px['day_idx'] = px.groupby(['stock_id', 'week_key']).cumcount()

    signals = build_signals(px)

    rows = []
    for (sid, wk), g in px.groupby(['stock_id', 'week_key'], sort=True):
        g = g[g['day_idx'] < 5]
        if len(g) < 3:
            continue
        week_start = g['trade_date'].iloc[0]
        sig = signals.get((sid, week_start.normalize()))
        if sig is None:
            continue
        rec = {'stock_id': sid, 'week_key': wk, 'week_start': week_start,
               'n_days': len(g), **sig}
        for i in range(5):
            if i < len(g):
                rec[f'c{i}'] = g['aclose'].iloc[i]
                rec[f'h{i}'] = g['ahigh'].iloc[i]
                rec[f'l{i}'] = g['alow'].iloc[i]
            else:   # 不足 5 天：以最後一個交易日補齊，等同「週五已收盤」
                rec[f'c{i}'] = g['aclose'].iloc[-1]
                rec[f'h{i}'] = g['ahigh'].iloc[-1]
                rec[f'l{i}'] = g['alow'].iloc[-1]
        rows.append(rec)

    d = pd.DataFrame(rows).sort_values(['week_start', 'stock_id']).reset_index(drop=True)
    return d.dropna(subset=['chip_p', 'pred_range', 'pred_vol'])


def build_signals(px: pd.DataFrame) -> dict:
    """
    重建歷史訊號：{(stock_id, 該週第一個交易日): {chip_p, pred_range, pred_vol}}

    **只用 M3 籌碼、振幅、波動三個模型**，不含 M1 LSTM 與 M2 新聞：
      M1 已實測等同天真基準，放進來只會增加雜訊
      M2 的新聞歷史只有數日，根本無法回測
    這也意味著回測涵蓋的角色比線上少兩個——報告裡會標明這個落差。
    """
    print('重建歷史訊號（籌碼機率 / 預測振幅 / 預測波動）…')
    sig_frames = []

    # 1. 籌碼機率：用已部署的 M3 bundle 對歷史面板批次推論
    chip = _chip_probability(px)

    # 2. 預測振幅：用已部署的振幅模型
    rng = _range_prediction()

    # 3. 預測波動：EWMA（波動率模型的部署版是模型與 EWMA 的組合，
    #    但 EWMA 本身在整段歷史上都算得出來，且是模型的官方對手基準）
    vol = _ewma_volatility(px)

    # 每個訊號各自做 as-of 對齊：三個模型的可用歷史長度差很多
    # （籌碼受限於 stock_chip_analysis、振幅受限於特徵窗），
    # 合併後再一起 dropna 會讓最短的那個決定全部樣本量。
    wk = px[['stock_id', 'trade_date', 'day_idx']]
    first_days = (wk[wk['day_idx'] == 0][['stock_id', 'trade_date']]
                  .sort_values(['stock_id', 'trade_date']))

    out = {}
    for name, frame in (('chip_p', chip), ('pred_range', rng), ('pred_vol', vol)):
        if frame is None or frame.empty:
            print(f'  ! {name} 無法重建——沒有它就沒有這個條件，策略會少一個把關')
            continue
        frame = frame.rename(columns={frame.columns[-1]: name}).dropna(subset=[name])
        for sid, g in frame.groupby('stock_id'):
            fd = first_days[first_days['stock_id'] == sid]['trade_date'].values
            if len(fd) == 0 or g.empty:
                continue
            g = g.sort_values('trade_date')
            gv = g['trade_date'].values
            vals = g[name].values
            # 對每個週首日，取「嚴格早於它」的最後一筆訊號——不得使用當週資訊
            idx = np.searchsorted(gv, fd, side='left') - 1
            for k, i in enumerate(idx):
                if i < 0:
                    continue
                key = (sid, pd.Timestamp(fd[k]).normalize())
                out.setdefault(key, {})[name] = float(vals[i])

    complete = {k: v for k, v in out.items()
                if all(s in v for s in ('chip_p', 'pred_range', 'pred_vol'))}
    print(f'  訊號覆蓋 {len(complete)} 個 (股票, 週) 組合'
          f'（三個訊號都齊全者；部分齊全 {len(out) - len(complete)} 個已剔除）')
    return complete


def _chip_probability(px):
    """用已部署的 M3 bundle 重建歷史 Buy 機率。"""
    try:
        import joblib
        import model_registry as registry
        from m3_features import build_panel
        from db.connection import get_conn

        path = registry.serving_path('m3_chip')
        bundle = joblib.load(path)
        with get_conn() as conn:
            raw = pd.read_sql("""
                SELECT c.stock_id, c.trade_date,
                       c.foreign_investor_buy AS foreign_net,
                       c.investment_trust_buy AS trust_net,
                       c.dealer_buy           AS dealer_net,
                       c.total_net_buy        AS total_net,
                       p.volume, p.close_price AS close
                  FROM stock_chip_analysis c
                  JOIN stock_daily_prices p USING (stock_id, trade_date)
                  JOIN stock_info s ON s.stock_id = c.stock_id AND s.is_tracking = true
                 ORDER BY c.stock_id, c.trade_date
            """, conn)
        if raw.empty:
            return None
        panel = build_panel(raw)
        cols = bundle['feature_cols']
        # 特徵含比值（如「淨額 ÷ 均量」），均量為 0 的停牌日會產生 inf，
        # sklearn 會直接拒絕整批推論。這些列本來就無效，剔除而非填補。
        panel[cols] = panel[cols].replace([np.inf, -np.inf], np.nan)
        panel = panel.dropna(subset=cols)
        if panel.empty:
            return None
        proba = bundle['model'].predict_proba(panel[cols].values)
        buy_idx = [k for k, v in bundle['label_map'].items() if v == 'Buy']
        col = buy_idx[0] if buy_idx else proba.shape[1] - 1
        out = panel[['stock_id', 'trade_date']].copy()
        out['trade_date'] = pd.to_datetime(out['trade_date'])
        out['chip_p'] = proba[:, col]
        print(f'  籌碼機率：{len(out)} 筆')
        return out
    except Exception as e:
        print(f'  ! 籌碼機率重建失敗：{e}')
        return None


def _range_prediction():
    """用已部署的振幅模型重建歷史預測振幅。"""
    try:
        import joblib
        import model_registry as registry
        from train_range import load_data

        bundle = joblib.load(registry.serving_path('range'))
        d = load_data(for_inference=True)
        cols = bundle['feature_cols']
        d = d.dropna(subset=cols)
        if d.empty:
            return None
        p = bundle['model'].predict(d[cols].values)
        out = d[['stock_id', 'trade_date']].copy()
        out['trade_date'] = pd.to_datetime(out['trade_date'])
        out['pred_range'] = np.exp(p) if bundle.get('log_target') else p
        print(f'  預測振幅：{len(out)} 筆')
        return out
    except Exception as e:
        print(f'  ! 振幅預測重建失敗：{e}')
        return None


def _ewma_volatility(px):
    """EWMA(λ=0.94) 日波動率——波動率模型的官方對手基準，全歷史都算得出來。"""
    lam = 0.94
    frames = []
    for sid, g in px.groupby('stock_id'):
        r = g['aclose'].pct_change().fillna(0.0).values
        var = np.zeros(len(r))
        acc = np.var(r[:20]) if len(r) > 20 else 1e-4
        for i in range(len(r)):
            acc = lam * acc + (1 - lam) * r[i] ** 2
            var[i] = acc
        frames.append(pd.DataFrame({'stock_id': sid, 'trade_date': g['trade_date'].values,
                                    'pred_vol': np.sqrt(var)}))
    out = pd.concat(frames, ignore_index=True)
    print(f'  EWMA 波動率：{len(out)} 筆')
    return out


# ── 策略模擬（向量化）─────────────────────────────────────────────────────────
def simulate(d: pd.DataFrame, p: dict) -> np.ndarray:
    """
    對面板中的每一週套用參數 p，回傳每週報酬（未進場的週為 NaN）。

    向量化是必要的：座標下降會評估上千組參數，逐週 Python 迴圈跑不完。
    """
    n = len(d)
    e = int(p['entry_day'])
    eligible = ((d['chip_p'].values >= p['buy_th']) &
                (d['pred_range'].values >= p['range_min']) &
                (d['pred_vol'].values <= p['vol_max']))
    if not eligible.any():
        return np.full(n, np.nan)

    entry = d[f'c{e}'].values.astype(float)
    vol = d['pred_vol'].values.astype(float)
    hold = int(p['max_hold'])
    # 停損距離沿用風險模組定義：σ × √持有天數
    stop_dist = p['stop_sigma'] * vol * math.sqrt(hold)
    stop_px = entry * (1 - stop_dist)
    take_px = entry * (1 + p['take_r'] * stop_dist)

    ret = np.full(n, np.nan)
    open_pos = eligible.copy()
    last_day = min(e + hold, 4)

    for day in range(e + 1, last_day + 1):
        if not open_pos.any():
            break
        lo = d[f'l{day}'].values.astype(float)
        hi = d[f'h{day}'].values.astype(float)
        cl = d[f'c{day}'].values.astype(float)

        # 同日兩者都觸及時保守認定先觸停損——日內順序不可知，
        # 樂觀假設會系統性高估策略表現
        hit_stop = open_pos & (lo <= stop_px)
        hit_take = open_pos & ~hit_stop & (hi >= take_px)

        ret[hit_stop] = stop_px[hit_stop] / entry[hit_stop] - 1
        ret[hit_take] = take_px[hit_take] / entry[hit_take] - 1
        open_pos = open_pos & ~hit_stop & ~hit_take

        if day == last_day:
            ret[open_pos] = cl[open_pos] / entry[open_pos] - 1
            open_pos = open_pos & False

    # 進場當天就是最後一天（e == 4）：以當日收盤進、當日收盤出 → 0 報酬
    still = eligible & np.isnan(ret)
    ret[still] = 0.0
    return ret


def evaluate(ret: np.ndarray, n_weeks: int, week_keys=None) -> dict:
    """
    把每週報酬換算成一組可比較的指標。

    **最大回撤必須以「投組」為單位算，不能把所有交易串成一條連續曲線。**
    同一週有二十幾檔股票同時在跑，串起來會把「同時發生的分散持倉」
    誤算成「連續二十幾次下注」，回撤動輒衝到 90% 以上——那是計算方式的產物，
    不是策略的真實風險。這裡先把同一週的所有交易平均成一筆投組週報酬，再複利。
    """
    mask = ~np.isnan(ret)
    r = ret[mask]
    n = len(r)
    trade_rate = n / max(n_weeks, 1)
    if n == 0:
        return {'trades': 0, 'trade_rate': 0.0, 'mean': 0.0, 'sortino': float('-inf'),
                'downside': 0.0, 'win_rate': 0.0, 'max_dd': 0.0, 'total': 0.0}

    mean = float(r.mean())
    downside = float(np.sqrt(np.mean(np.minimum(r, 0.0) ** 2)))
    sortino = mean / downside if downside > 1e-9 else (mean * 1e3 if mean > 0 else 0.0)

    if week_keys is not None:
        wk = np.asarray(week_keys)[mask]
        order = np.argsort(wk, kind='stable')
        wk, rr = wk[order], r[order]
        uniq, idx = np.unique(wk, return_index=True)
        port = np.array([seg.mean() for seg in np.split(rr, idx[1:])])
    else:
        port = r
    equity = np.cumprod(1 + port)
    peak = np.maximum.accumulate(equity)
    max_dd = float(np.max(1 - equity / peak)) if len(equity) else 0.0
    return {
        'trades': n, 'trade_rate': trade_rate, 'mean': mean,
        'downside': downside, 'sortino': float(sortino),
        'win_rate': float((r > 0).mean()), 'max_dd': max_dd,
        'total': float(equity[-1] - 1),
    }


def objective(d: pd.DataFrame, p: dict) -> float:
    """
    「最小虧損風險下的最大利益」→ Sortino，但出手率過低直接判為不可用。

    不用平均報酬當目標：那會選出「重押少數幾次剛好賭中」的參數。
    不用單純的勝率：勝率高但輸大賺小的策略是虧的。
    """
    m = evaluate(simulate(d, p), len(d), d['week_key'].values)
    if m['trade_rate'] < MIN_TRADE_RATE:
        return float('-inf')
    return m['sortino']


# ── 迭代優化（座標下降 + 多起點，收斂即止）────────────────────────────────────
def optimise(d: pd.DataFrame, seed: int = 0, verbose: bool = True) -> tuple:
    """
    回傳 (最佳參數, 最佳目標值, 迭代紀錄)。

    「到極限」的定義：連續 CONVERGE_PATIENCE 輪目標改善 < CONVERGE_EPS。
    這是可驗證的停止條件，不是跑固定圈數然後宣稱已收斂。
    """
    rng_ = np.random.RandomState(seed)
    best_p = {k: v[rng_.randint(len(v))] for k, v in PARAM_GRID.items()}
    best_v = objective(d, best_p)
    history = [{'round': 0, 'objective': best_v, 'params': dict(best_p)}]

    stale, rnd = 0, 0
    while stale < CONVERGE_PATIENCE and rnd < 20:
        rnd += 1
        prev = best_v
        for key in PARAM_ORDER:
            cur = best_p[key]
            for cand in PARAM_GRID[key]:
                if cand == cur:
                    continue
                trial = dict(best_p, **{key: cand})
                v = objective(d, trial)
                if v > best_v + 1e-12:
                    best_v, best_p = v, trial
        # 起點可能落在「出手率過低」的不可行區，此時目標恆為 −inf。
        # 若掃完一整輪仍走不出不可行區，再掃下去也不會有結果——
        # 直接判定此起點失敗，交給下一個起點，別空轉滿 20 輪。
        if not np.isfinite(best_v):
            if verbose:
                print(f'    第 {rnd} 輪：仍在不可行區（出手率 < {MIN_TRADE_RATE:.0%}），放棄此起點')
            break
        gain = best_v - prev if np.isfinite(prev) else float('inf')
        history.append({'round': rnd, 'objective': best_v, 'gain': gain,
                        'params': dict(best_p)})
        if verbose:
            print(f'    第 {rnd} 輪：目標 {best_v:.4f}（改善 {gain:+.5f}）')
        stale = stale + 1 if gain < CONVERGE_EPS else 0
    return best_p, best_v, history


def optimise_multi(d: pd.DataFrame, verbose=True) -> tuple:
    """多起點：座標下降會停在局部最優，換起點是最便宜的緩解方式。"""
    best = (None, float('-inf'), [])
    for s in range(N_RESTARTS):
        if verbose:
            print(f'  起點 {s + 1}/{N_RESTARTS}')
        p, v, h = optimise(d, seed=s, verbose=verbose)
        if v > best[1]:
            best = (p, v, h)
    return best


# ── 基準 ──────────────────────────────────────────────────────────────────────
def baseline_buy_hold(d: pd.DataFrame) -> dict:
    """週一收盤買、週五收盤賣。這是「什麼都不判斷」的對照組。"""
    r = (d['c4'].values.astype(float) / d['c0'].values.astype(float)) - 1
    return evaluate(r, len(d), d['week_key'].values)


def baseline_always_flat(d: pd.DataFrame) -> dict:
    """完全不交易。風險為零、報酬為零——用來提醒 Sortino 高不等於有用。"""
    return {'trades': 0, 'trade_rate': 0.0, 'mean': 0.0, 'downside': 0.0,
            'sortino': 0.0, 'win_rate': 0.0, 'max_dd': 0.0, 'total': 0.0}


def baseline_random(d: pd.DataFrame, seed=0) -> dict:
    """隨機以相同出手率進場、持有到週五。用來檢查優勢是否只是進場頻率造成的。"""
    rs = np.random.RandomState(seed)
    mask = rs.rand(len(d)) < 0.3
    r = np.full(len(d), np.nan)
    r[mask] = (d['c4'].values[mask].astype(float) / d['c0'].values[mask].astype(float)) - 1
    return evaluate(r, len(d), d['week_key'].values)


# ── 走查 ──────────────────────────────────────────────────────────────────────
def walk_forward(d: pd.DataFrame) -> tuple:
    """
    擴張視窗：第 k 折用前 k 段優化參數、在第 k+1 段評分。

    在訓練期上調出來的分數不算數——本專案從 Iteration 9 起就是這個規矩。
    """
    weeks = np.sort(d['week_start'].unique())
    bounds = [int(len(weeks) * (i + 1) / (N_FOLDS + 1)) for i in range(N_FOLDS)]
    rows = []
    for i, b in enumerate(bounds):
        end = int(len(weeks) * (i + 2) / (N_FOLDS + 1))
        tr = d[d['week_start'] < weeks[b]]
        te = d[(d['week_start'] >= weeks[b]) & (d['week_start'] < weeks[min(end, len(weeks) - 1)])]
        if len(tr) < 200 or len(te) < 50:
            continue
        print(f'  折 {i + 1}/{N_FOLDS}：訓練 {len(tr)} 週樣本 → 測試 {len(te)} 週樣本')
        p, v_in, _ = optimise_multi(tr, verbose=False)
        m_out = evaluate(simulate(te, p), len(te), te['week_key'].values)
        bh = baseline_buy_hold(te)
        rows.append({'fold': i + 1, 'params': p, 'in_sample': v_in,
                     'out': m_out, 'buy_hold': bh,
                     'test_from': str(pd.Timestamp(weeks[b]).date()),
                     'test_to': str(pd.Timestamp(weeks[min(end, len(weeks) - 1)]).date())})
        print(f'    外樣本 Sortino {m_out["sortino"]:.3f}（買進持有 {bh["sortino"]:.3f}）'
              f'　平均週報酬 {m_out["mean"]:+.3%}　出手率 {m_out["trade_rate"]:.0%}')
    return rows


# ── 主流程 ────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description='週交易計畫策略優化')
    ap.add_argument('--quick', action='store_true', help='只用近 10 年資料')
    ap.add_argument('--start', default=None, help='起始日期 YYYY-MM-DD')
    args = ap.parse_args()

    start = args.start or ('2016-01-01' if args.quick else None)
    print('載入週面板…')
    d = load_weekly_panel(start)
    print(f'週樣本 {len(d)} 筆 / {d["stock_id"].nunique()} 檔　'
          f'{d["week_start"].min().date()} ~ {d["week_start"].max().date()}')
    if len(d) < 500:
        print('樣本不足，中止。')
        return

    print('\n擴張視窗走查（參數只在訓練期優化）…')
    folds = walk_forward(d)
    if not folds:
        print('走查折數不足，中止。')
        return

    out_sortino = float(np.mean([f['out']['sortino'] for f in folds]))
    out_mean = float(np.mean([f['out']['mean'] for f in folds]))
    bh_sortino = float(np.mean([f['buy_hold']['sortino'] for f in folds]))
    bh_mean = float(np.mean([f['buy_hold']['mean'] for f in folds]))

    print('\n全樣本迭代優化（產出部署參數；分數不作為績效宣稱）…')
    best_p, best_v, history = optimise_multi(d, verbose=True)
    full = evaluate(simulate(d, best_p), len(d), d['week_key'].values)

    deploy = (out_sortino > bh_sortino + DEPLOY_MARGIN) and (out_mean > 0)
    reason = (f'外樣本 Sortino {out_sortino:.3f} vs 買進持有 {bh_sortino:.3f}'
              f'（需高出 {DEPLOY_MARGIN}），平均週報酬 {out_mean:+.3%}')
    print(f'\n部署判定：{"通過" if deploy else "未通過"} — {reason}')

    save_policy(best_p, full, folds, out_sortino, bh_sortino, deploy, history)
    write_report(d, best_p, full, folds, out_sortino, out_mean,
                 bh_sortino, bh_mean, deploy, reason, history)


def save_policy(p, full, folds, out_sortino, bh_sortino, deploy, history):
    import joblib
    os.makedirs(MODEL_DIR, exist_ok=True)
    path = os.path.join(MODEL_DIR, 'weekly_policy.joblib')
    joblib.dump({
        'params': p,
        'trained_at': datetime.now().isoformat(),
        'full_sample_metrics': full,
        'walk_forward_sortino': out_sortino,
        'buy_hold_sortino': bh_sortino,
        # 推論端必須讀這個旗標。未通過走查的策略仍會存檔（供檢視），
        # 但線上只能以「參考」呈現，不能當成建議送出。
        'deploy': bool(deploy),
        'converged_rounds': len(history) - 1,
        'signals_used': ['chip_p', 'pred_range', 'pred_vol'],
        'signals_missing_vs_online': ['M1 趨勢', 'M2 消息面'],
    }, path)
    print(f'策略已存 {path}（deploy={deploy}）')


def write_report(d, p, full, folds, out_sortino, out_mean,
                 bh_sortino, bh_mean, deploy, reason, history):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'weekly_policy.md')
    lines = [
        '# 週交易計畫策略（Iteration 22）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**樣本：** {len(d)} 個 (股票, 週) / {d["stock_id"].nunique()} 檔　'
        f'{d["week_start"].min().date()} ~ {d["week_start"].max().date()}',
        f'**驗證：** {N_FOLDS} 折擴張視窗走查，參數只在訓練期優化',
        f'**收斂：** 座標下降，連續 {CONVERGE_PATIENCE} 輪改善 < {CONVERGE_EPS} 即停；'
        f'{N_RESTARTS} 個起點取最佳（全樣本共 {len(history) - 1} 輪收斂）',
        '',
        '## 走查結果（外樣本）',
        '',
        '| 折 | 測試期間 | 策略 Sortino | 買進持有 Sortino | 策略平均週報酬 | 買進持有 | 出手率 | 最大回撤 |',
        '|----|---------|------------|----------------|--------------|---------|--------|---------|',
    ]
    for f in folds:
        o, b = f['out'], f['buy_hold']
        lines.append(f"| {f['fold']} | {f['test_from']}~{f['test_to']} | "
                     f"{o['sortino']:.3f} | {b['sortino']:.3f} | "
                     f"{o['mean']:+.3%} | {b['mean']:+.3%} | "
                     f"{o['trade_rate']:.0%} | {o['max_dd']:.1%} |")
    lines += [
        '',
        f'**平均外樣本 Sortino {out_sortino:.3f}　買進持有 {bh_sortino:.3f}**',
        f'　平均週報酬 {out_mean:+.3%}　買進持有 {bh_mean:+.3%}',
        '',
        '## 部署參數（全樣本優化）',
        '',
        '| 參數 | 值 | 意義 |',
        '|------|-----|------|',
        f"| entry_day | {p['entry_day']} | 週內第 {p['entry_day'] + 1} 個交易日收盤進場 |",
        f"| buy_th | {p['buy_th']} | 籌碼模型 Buy 機率門檻 |",
        f"| range_min | {p['range_min']} | 預測週振幅下限（低於此不進場） |",
        f"| vol_max | {p['vol_max']} | 預測日波動率上限 |",
        f"| stop_sigma | {p['stop_sigma']} | 停損 = σ × √持有天數 的倍數 |",
        f"| take_r | {p['take_r']} | 停利 = take_r × 停損距離 |",
        f"| max_hold | {p['max_hold']} | 最多持有 {p['max_hold']} 個交易日 |",
        '',
        f"全樣本表現（**非績效宣稱**，參數是在同一批資料上調出來的）："
        f"Sortino {full['sortino']:.3f}、平均週報酬 {full['mean']:+.3%}、"
        f"勝率 {full['win_rate']:.1%}、出手率 {full['trade_rate']:.0%}、"
        f"最大回撤 {full['max_dd']:.1%}",
        '',
        '## 部署判定',
        '',
        f'**{"通過" if deploy else "未通過"}** — {reason}',
        '',
        '## 這個回測沒有涵蓋什麼',
        '',
        '- **M1 趨勢與 M2 消息面兩個角色不在回測內。** M1 已實測等同天真基準，'
        '放進來只是增加雜訊；M2 的新聞歷史僅數日，根本無法回測。'
        '線上決策會多這兩個角色，因此線上行為與此回測**並非同一件事**。',
        '- **未計入交易成本與滑價。** 台股來回手續費加證交稅約 0.44%，'
        '出手率越高、這個缺口越致命。上表的報酬要先減掉它才是實際入袋的數字。',
        '- **假設能以當日收盤價成交。** 實際上收盤競價未必成交在該價位。',
        '- **同日觸及停損與停利時一律認定停損先發生。** 這是保守假設；'
        '真實的日內順序不可知，樂觀假設會系統性高估表現。',
    ]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'報告已寫入 {path}')


if __name__ == '__main__':
    main()
