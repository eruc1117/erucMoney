"""
每週自動預測（Iteration 37）
────────────────────────────
需求：每星期日，用所有可用模型對所有已有股票預測「下一週」與「下下週」，
直接顯示，不用人工觸發。

## 誰算「所有可用模型」

`model_catalog.CATALOG` 裡的每一個：台股是跳空、振幅、波動率、成交量、M3 籌碼、
M2 新聞、十個 LSTM；美股是美股跳空與十個 LSTM。每個模型有自己的視野：

| 模型 | 視野 | 涵蓋 |
|------|------|------|
| LSTM ×10 | 逐日收盤，這裡要 10 個交易日 | 下週（第 1~5 日）與下下週（第 6~10 日） |
| 波動率 | 未來 20 日已實現波動 | 兩週都在裡面 |
| 振幅、成交量 | 未來 5 日 | 只有下週 |
| M3、M2 | 未來 3 日方向 | 下週前半 |
| 跳空 | 次一交易日開盤 | 下週第一天 |

視野不到下下週的模型，畫面就標「只涵蓋下週」，不硬湊。

## 為什麼存表而不是每次現算

十個 LSTM × 49 檔 × 10 日的推論要幾分鐘，且 HTTP 打到 :8001。
週日算一次存起來，頁面開了就顯示；`model_predictions` 台帳照常由各模型自己寫
（批次模型的 `_log_all` 是 upsert，同一基準日重跑不會重複）。

## 時序

排程週日 08:00。程序若週日沒在跑，啟動時 `due()` 會發現「上個週日 08:00 以來沒有執行紀錄」
就補跑一次（`scheduler._catch_up`）。
"""

import json
import logging
import statistics
import threading
from datetime import date, datetime, timedelta

import requests

from db.connection import get_conn

logger = logging.getLogger(__name__)

LSTM_BASE_URL = 'http://localhost:8001'
LSTM_DAYS = 10
RUN_WEEKDAY, RUN_HOUR = 6, 8          # 週日 08:00

LSTM_KEYS = ['m01_vanilla', 'm02_stacked', 'm03_bidirectional', 'm04_attention',
             'm05_cnn_lstm', 'm06_multifeature', 'm07_seq2seq', 'm08_mc_dropout',
             'm09_technical', 'm10_ensemble']

_lock = threading.Lock()
_state = {'running': False, 'started_at': None, 'last_error': None}

DDL = """
CREATE TABLE IF NOT EXISTS weekly_forecast_runs (
    id SERIAL PRIMARY KEY,
    run_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    trigger VARCHAR(16) NOT NULL DEFAULT 'schedule',
    base_date DATE,
    week1_start DATE NOT NULL, week1_end DATE NOT NULL,
    week2_start DATE NOT NULL, week2_end DATE NOT NULL,
    n_stocks INTEGER NOT NULL DEFAULT 0, n_models INTEGER NOT NULL DEFAULT 0,
    n_rows INTEGER NOT NULL DEFAULT 0,
    errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    finished_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS weekly_forecasts (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES weekly_forecast_runs(id) ON DELETE CASCADE,
    market VARCHAR(4) NOT NULL, stock_id VARCHAR(10) NOT NULL,
    model_key VARCHAR(40) NOT NULL, payload JSONB NOT NULL,
    UNIQUE (run_id, market, stock_id, model_key)
);
CREATE INDEX IF NOT EXISTS idx_weekly_forecasts_run ON weekly_forecasts (run_id, market);
"""


def _ensure_tables():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
        conn.commit()


# ── 週區間 ──────────────────────────────────────────────────────────────────
def week_windows(today: date = None) -> dict:
    """
    以「最近一個週日（含今天）」為錨：下一週 = 週一到週五，下下週 = 再下一個週一到週五。
    補跑若落在週間，下一週就是本週剩下的日子——區間照實記錄，畫面照實顯示。
    """
    today = today or date.today()
    last_sunday = today - timedelta(days=(today.weekday() + 1) % 7)
    w1 = last_sunday + timedelta(days=1)
    return {'week1_start': w1, 'week1_end': w1 + timedelta(days=4),
            'week2_start': w1 + timedelta(days=7), 'week2_end': w1 + timedelta(days=11)}


def last_due_time(now: datetime = None) -> datetime:
    """上一個（含現在）該執行的時間點：最近的週日 08:00。"""
    now = now or datetime.now()
    d = now.date() - timedelta(days=(now.weekday() + 1) % 7)
    due = datetime.combine(d, datetime.min.time()).replace(hour=RUN_HOUR)
    if due > now:
        due -= timedelta(days=7)
    return due


def next_run_time(now: datetime = None) -> datetime:
    return last_due_time(now) + timedelta(days=7)


def due() -> bool:
    """上個週日 08:00 以來沒有完成的執行 → 該補跑。"""
    _ensure_tables()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT max(finished_at) FROM weekly_forecast_runs WHERE finished_at IS NOT NULL")
            last = cur.fetchone()[0]
    return last is None or last < last_due_time()


# ── 股票清單 ────────────────────────────────────────────────────────────────
def _universe() -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stock_id, stock_name FROM stock_info WHERE is_tracking = TRUE ORDER BY stock_id")
            tw = [{'stock_id': r[0].strip(), 'name': r[1]} for r in cur.fetchall()]
            cur.execute("SELECT ticker, name FROM us_tickers WHERE is_tracking = TRUE ORDER BY ticker")
            us = [{'stock_id': r[0].strip().upper(), 'name': r[1]} for r in cur.fetchall()]
            cur.execute("""SELECT DISTINCT ON (stock_id) stock_id, trade_date::text, close_price
                           FROM stock_daily_prices ORDER BY stock_id, trade_date DESC""")
            tw_close = {r[0].strip(): (r[1], float(r[2])) for r in cur.fetchall() if r[2]}
            cur.execute("""SELECT DISTINCT ON (ticker) ticker, trade_date::text, close_price
                           FROM us_daily_prices ORDER BY ticker, trade_date DESC""")
            us_close = {r[0].strip().upper(): (r[1], float(r[2])) for r in cur.fetchall() if r[2]}
    for s in tw:
        s['last_date'], s['close'] = tw_close.get(s['stock_id'], (None, None))
    for s in us:
        s['last_date'], s['close'] = us_close.get(s['stock_id'], (None, None))
    return {'tw': tw, 'us': us}


# ── 各模型 ──────────────────────────────────────────────────────────────────
def _lstm(stock_id, model_key, market, base_close, win):
    r = requests.get(f'{LSTM_BASE_URL}/model/predict',
                     params={'stock_id': stock_id, 'model': model_key,
                             'days': LSTM_DAYS, 'market': market}, timeout=120)
    if r.status_code != 200:
        try:
            detail = r.json().get('detail', '')
        except Exception:
            detail = r.text[:120]
        raise RuntimeError(f'HTTP {r.status_code} {detail}')
    path = r.json()
    w1e, w2e = win['week1_end'].isoformat(), win['week2_end'].isoformat()

    def pick(items):
        if not items:
            return None
        last = items[-1]
        chg = ((last['predicted_close'] / base_close - 1) * 100) if base_close else None
        return {'date': last['date'], 'close': last['predicted_close'],
                'ci_low': last.get('ci_low'), 'ci_high': last.get('ci_high'),
                'chg_pct': round(chg, 2) if chg is not None else None, 'n_days': len(items)}

    week1 = [p for p in path if p['date'] <= w1e]
    week2 = [p for p in path if w1e < p['date'] <= w2e]
    return {'base_close': base_close, 'path': path, 'week1': pick(week1), 'week2': pick(week2)}


def _batch_tw():
    """台股的批次模型：一次算全部股票，回 {model_key: {stock_id: payload}}。"""
    out, errors = {}, []

    try:
        import gap_model
        g = gap_model.predict_gaps()
        if g.get('available'):
            out['gap'] = {p['stock_id']: {
                'gap_pct': p['gap_pct'], 'direction': p['direction'],
                'implied_open': p['implied_open'], 'covers': 'next_day',
                # 2026-09-20 的準確度報告：線上推論的夜盤特徵沒換成最新一場，
                # 這個值可能對應已發生的跳空。修好前照實標出來。
                'caveat': '線上時序待修：此值可能對應已發生的跳空（見 AI/Doc/ModelAccuracy.md）',
            } for p in g['predictions']}
        else:
            errors.append(f"gap: {g.get('reason')}")
    except Exception as e:
        errors.append(f'gap: {e}')

    try:
        import range_model
        r = range_model.predict_ranges()
        if r.get('available'):
            out['range'] = {p['stock_id']: {
                'range_pct': p['range_pct'], 'hist_median_pct': p['hist_median_pct'],
                'self_ratio': p['self_ratio'], 'peer_pct': p['peer_pct'],
                'is_significant': p['is_significant'],
                'expected_high': p['expected_high'], 'expected_low': p['expected_low'],
                'covers': 'week1'} for p in r['results']}
        else:
            errors.append(f"range: {r.get('reason')}")
    except Exception as e:
        errors.append(f'range: {e}')

    try:
        import volume_model
        v = volume_model.get_liquidity()
        if v.get('results'):
            out['volume'] = {sid: {
                'vol_multiple': p['vol_multiple'], 'liquidity': p['liquidity'],
                'expected_daily_volume': p['expected_daily_volume'],
                'avg_volume_20d': p['avg_volume_20d'], 'covers': 'week1'}
                for sid, p in v['results'].items()}
        else:
            errors.append(f"volume: 不可用（{v.get('engine')}）")
    except Exception as e:
        errors.append(f'volume: {e}')

    return out, errors


def _batch_us():
    out, errors = {}, []
    try:
        import us_model
        g = us_model.predict_gaps()
        if g.get('available'):
            out['us_gap'] = {p['ticker']: {
                'gap_pct': p['gap_pct'], 'direction': p['direction'],
                'magnitude': p['magnitude'], 'implied_open': p['implied_open'],
                'target_session': g.get('target_session'), 'covers': 'next_day'}
                for p in g['predictions']}
        else:
            errors.append(f"us_gap: {g.get('reason')}")
    except Exception as e:
        errors.append(f'us_gap: {e}')
    return out, errors


def _per_stock_tw(stock_id):
    """逐檔模型：波動率、M3、M2。各自失敗各自記。"""
    rows, errors = {}, []
    try:
        import risk_model
        rk = risk_model.get_risk(stock_id)
        if rk.get('predicted_vol') is not None:
            rows['volatility'] = {
                'predicted_vol': rk['predicted_vol'], 'vol_regime': rk['vol_regime'],
                'stop_pct': rk['stop_pct'], 'position_pct': rk['position_pct'],
                'engine': rk['engine'], 'covers': 'both'}
        else:
            errors.append(f"volatility/{stock_id}: {rk.get('reason')}")
    except Exception as e:
        errors.append(f'volatility/{stock_id}: {e}')
    try:
        import model3_chip
        m3 = model3_chip.get_signal(stock_id)
        rows['m3_chip'] = {'signal': m3.get('signal'), 'confidence': m3.get('confidence'),
                           'reason': m3.get('reason'), 'engine': m3.get('engine'), 'covers': '3d'}
    except Exception as e:
        errors.append(f'm3_chip/{stock_id}: {e}')
    try:
        import model2_news
        m2 = model2_news.get_signal(stock_id)
        rows['m2_news'] = {'signal': m2.get('signal'), 'confidence': m2.get('confidence'),
                           'reason': m2.get('reason'), 'covers': '3d'}
    except Exception as e:
        errors.append(f'm2_news/{stock_id}: {e}')
    return rows, errors


# ── 主流程 ──────────────────────────────────────────────────────────────────
def run(trigger: str = 'schedule') -> dict:
    """跑全部模型、全部股票，寫入資料庫。回傳執行摘要。"""
    with _lock:
        if _state['running']:
            return {'status': 'already_running'}
        _state.update(running=True, started_at=datetime.now().isoformat(), last_error=None)
    try:
        return _run_inner(trigger)
    except Exception as e:
        _state['last_error'] = str(e)
        logger.exception('[weekly] 執行失敗')
        raise
    finally:
        with _lock:
            _state['running'] = False


def _run_inner(trigger):
    _ensure_tables()
    win = week_windows()
    uni = _universe()
    base_dates = [s['last_date'] for s in uni['tw'] if s['last_date']]
    base_date = max(base_dates) if base_dates else None

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO weekly_forecast_runs
                           (trigger, base_date, week1_start, week1_end, week2_start, week2_end)
                           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                        (trigger, base_date, win['week1_start'], win['week1_end'],
                         win['week2_start'], win['week2_end']))
            run_id = cur.fetchone()[0]
        conn.commit()
    logger.info('[weekly] run %d 開始（%s）：台股 %d 檔、美股 %d 檔，下週 %s~%s',
                run_id, trigger, len(uni['tw']), len(uni['us']),
                win['week1_start'], win['week1_end'])

    rows, errors, models_seen = [], [], set()

    def add(market, sid, key, payload):
        rows.append((run_id, market, sid, key, json.dumps(payload, ensure_ascii=False, default=str)))
        models_seen.add(f'{market}:{key}')

    # 批次模型
    b, errs = _batch_tw(); errors += errs
    for key, per in b.items():
        for sid, payload in per.items():
            add('tw', sid, key, payload)
    b, errs = _batch_us(); errors += errs
    for key, per in b.items():
        for sid, payload in per.items():
            add('us', sid, key, payload)

    # 逐檔模型
    for s in uni['tw']:
        per, errs = _per_stock_tw(s['stock_id']); errors += errs
        for key, payload in per.items():
            add('tw', s['stock_id'], key, payload)

    # LSTM：台股與美股各十個
    lstm_ok = True
    try:
        requests.get(f'{LSTM_BASE_URL}/health', timeout=5)
    except Exception as e:
        lstm_ok = False
        errors.append(f'lstm: 預測服務 :8001 未啟動（{e.__class__.__name__}），十個 LSTM 全部略過')
    if lstm_ok:
        for market, prefix in (('tw', 'lstm'), ('us', 'lstm_us')):
            for s in uni[market]:
                for mk in LSTM_KEYS:
                    try:
                        add(market, s['stock_id'], f'{prefix}:{mk}',
                            _lstm(s['stock_id'], mk, market, s['close'], win))
                    except Exception as e:
                        errors.append(f'{prefix}:{mk}/{s["stock_id"]}: {str(e)[:100]}')

    with get_conn() as conn:
        with conn.cursor() as cur:
            from psycopg2.extras import execute_values
            execute_values(cur, """INSERT INTO weekly_forecasts (run_id, market, stock_id, model_key, payload)
                                   VALUES %s ON CONFLICT (run_id, market, stock_id, model_key) DO UPDATE
                                   SET payload = EXCLUDED.payload""",
                           rows, template='(%s, %s, %s, %s, %s::jsonb)')
            cur.execute("""UPDATE weekly_forecast_runs SET n_stocks=%s, n_models=%s, n_rows=%s,
                           errors=%s::jsonb, finished_at=CURRENT_TIMESTAMP WHERE id=%s""",
                        (len(uni['tw']) + len(uni['us']), len(models_seen), len(rows),
                         json.dumps(errors[:200], ensure_ascii=False), run_id))
        conn.commit()
    logger.info('[weekly] run %d 完成：%d 列、%d 個模型、%d 個錯誤',
                run_id, len(rows), len(models_seen), len(errors))
    return {'status': 'done', 'run_id': run_id, 'rows': len(rows),
            'models': len(models_seen), 'errors': len(errors)}


def status() -> dict:
    with _lock:
        return dict(_state, next_run=next_run_time().isoformat(timespec='minutes'))


# ── 讀取（頁面用）──────────────────────────────────────────────────────────
def _median(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 2) if xs else None


def latest() -> dict:
    """最新一次完成的執行，整理成每檔一列。"""
    _ensure_tables()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, run_at, trigger, base_date::text, week1_start::text, week1_end::text,
                                  week2_start::text, week2_end::text, n_stocks, n_models, n_rows, errors, finished_at
                           FROM weekly_forecast_runs WHERE finished_at IS NOT NULL
                           ORDER BY finished_at DESC LIMIT 1""")
            r = cur.fetchone()
            if not r:
                return {'available': False, 'reason': '尚未有任何執行；排程每週日 08:00 自動跑',
                        'next_run': next_run_time().isoformat(timespec='minutes'), 'status': status()}
            run = {'id': r[0], 'run_at': r[1].isoformat(timespec='minutes'), 'trigger': r[2],
                   'base_date': r[3], 'week1': {'start': r[4], 'end': r[5]},
                   'week2': {'start': r[6], 'end': r[7]}, 'n_stocks': r[8], 'n_models': r[9],
                   'n_rows': r[10], 'errors': r[11] or [], 'finished_at': r[12].isoformat(timespec='minutes')}
            cur.execute("SELECT market, stock_id, model_key, payload FROM weekly_forecasts WHERE run_id = %s", (r[0],))
            frows = cur.fetchall()

    uni = _universe()
    names = {(m, s['stock_id']): s for m in ('tw', 'us') for s in uni[m]}
    by = {}
    for market, sid, key, payload in frows:
        by.setdefault((market, sid), {})[key] = payload

    markets = {'tw': [], 'us': []}
    for (market, sid), models in by.items():
        info = names.get((market, sid), {'stock_id': sid, 'name': sid, 'close': None, 'last_date': None})
        prefix = 'lstm:' if market == 'tw' else 'lstm_us:'
        lstm = {k.split(':', 1)[1]: v for k, v in models.items() if k.startswith(prefix)}
        w1 = [v['week1']['chg_pct'] for v in lstm.values() if v.get('week1')]
        w2 = [v['week2']['chg_pct'] for v in lstm.values() if v.get('week2')]
        row = {
            'stock_id': sid, 'name': info.get('name'), 'close': info.get('close'),
            'last_date': info.get('last_date'),
            'lstm': {
                'models': {k: {'week1': v.get('week1'), 'week2': v.get('week2')} for k, v in lstm.items()},
                'n_models': len(lstm),
                'week1': {'median_chg_pct': _median(w1), 'min_chg_pct': min(w1) if w1 else None,
                          'max_chg_pct': max(w1) if w1 else None, 'n_up': sum(1 for x in w1 if x > 0)},
                'week2': {'median_chg_pct': _median(w2), 'min_chg_pct': min(w2) if w2 else None,
                          'max_chg_pct': max(w2) if w2 else None, 'n_up': sum(1 for x in w2 if x > 0)},
            },
            'gap': models.get('gap') or models.get('us_gap'),
            'range': models.get('range'), 'volatility': models.get('volatility'),
            'volume': models.get('volume'), 'm3_chip': models.get('m3_chip'),
            'm2_news': models.get('m2_news'),
        }
        markets[market].append(row)
    for m in markets:
        markets[m].sort(key=lambda x: x['stock_id'])

    return {'available': True, 'run': run, 'markets': markets,
            'next_run': next_run_time().isoformat(timespec='minutes'),
            'schedule': '每週日 08:00 自動執行；程序啟動時若上個週日沒跑會補跑',
            'status': status()}


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    print(run(trigger='manual'))
