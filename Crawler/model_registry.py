"""
模型版本登錄（Iteration 21）
────────────────────────────
在此之前，本專案所有模型都是「固定檔名、重訓直接覆寫」：

    UnifiedModel/saved_models/range_model.joblib
    UnifiedModel/saved_models/volatility.joblib
    UnifiedModel/saved_models/gap_model.joblib
    RandomForest/saved_models/m3_chip_rf.joblib
    LSTM/saved_models/<model_key>/<stock_id>.keras

重訓一次，上一版就永久消失；線上那筆預測是哪一版算的也無從追溯。
這讓「這個模型到底有沒有用」這個問題在資料上根本無法回答——
而本專案的每一次結論翻案（Iteration 11、15、20）都是靠可回溯的量測。

## 三種狀態

    candidate   正在迭代的版本。artifact_path 指向**工作區**檔案，
                下次重訓就直接覆寫它。每個類型同時只有一個。
    frozen      已凍結的長期服役版本。artifact_path 指向
                `saved_models/_versions/<type>/v<N>/` 底下的**不可變快照**，
                訓練腳本碰不到它。凍結後自動開出 v+1 candidate。
    retired     曾經服役、已被使用者換下的版本（檔案保留，供回溯）。

`is_serving` 標記推論端實際載入哪一版：凍結後即為該凍結版本，
在有任何凍結版本之前則回退到 candidate（否則新專案第一天就無模型可用）。

## 設計上的取捨

**凍結採「快照複製」而非「訓練寫新版本號」。** 後者要改動全部五套訓練腳本
（LSTM 那套是 8 個模型 × 22 檔的 keras 目錄），而前者只需在凍結那一刻複製一次。
代價是：candidate 在被凍結前的中間狀態不會留存——這是刻意的，
沒被選中的中間版本本來就沒有保留價值。

## 對外界的容錯

推論端在資料庫不可用時**必須照常運作**。所有查詢失敗都回退到工作區路徑，
只記 warning 不拋例外。寫入台帳失敗同理——記錄預測是附帶效果，不能拖垮預測本身。
"""

import logging
import os
import shutil

logger = logging.getLogger(__name__)

_BASE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_BASE, '..'))


def _p(*parts):
    return os.path.normpath(os.path.join(_ROOT, *parts))


# ── 已知模型類型 ──────────────────────────────────────────────────────────────
# workspace：訓練腳本實際寫出的路徑（檔案或目錄）
# target_kind：預測標的種類，決定實際值怎麼回填、方向怎麼判定
#   close      逐日收盤價（LSTM）           → 方向＝與基準日收盤比較漲跌
#   range      未來 N 日振幅比例             → 無方向，只比大小（排序用）
#   volatility 未來 N 日已實現波動率         → 同上
#   gap        次一交易日開盤跳空幅度         → 方向＝跳空正負
#   signal     買／賣／觀望訊號              → 方向＝訊號本身
# `logs_ledger`：這個類型的推論端是否會寫 `model_predictions`。
# 稽核（`ledger_audit.py`）要據此判斷「沒有紀錄」是異常還是本來就不寫；
# 少了這個旗標就只能用猜的，10 個 LSTM 類型會天天誤報。
MODEL_TYPES = {
    'range': {
        'label': '週振幅預測',
        'workspace': _p('UnifiedModel', 'saved_models', 'range_model.joblib'),
        'target_kind': 'range',
        'horizon_days': 5,
        'logs_ledger': True,
    },
    'volatility': {
        'label': '波動率（風險模組）',
        'workspace': _p('UnifiedModel', 'saved_models', 'volatility.joblib'),
        'target_kind': 'volatility',
        'horizon_days': 20,
        'logs_ledger': True,
    },
    'gap': {
        'label': '開盤跳空預測',
        'workspace': _p('UnifiedModel', 'saved_models', 'gap_model.joblib'),
        'target_kind': 'gap',
        'horizon_days': 1,
        'logs_ledger': True,
    },
    'm3_chip': {
        'label': 'M3 籌碼 Random Forest',
        'workspace': _p('RandomForest', 'saved_models', 'm3_chip_rf.joblib'),
        'target_kind': 'signal',
        'horizon_days': 3,
        'logs_ledger': True,
    },
    'volume': {
        'label': '成交量預測（流動性模組）',
        'workspace': _p('UnifiedModel', 'saved_models', 'volume.joblib'),
        'target_kind': 'volume',
        'horizon_days': 5,
        'logs_ledger': True,
    },
    # 美股跳空與台股跳空的公式相同，但 target_kind 刻意分開：回填要去
    # `us_daily_prices` 取價，混用一個 kind 會讓回填端得靠猜 stock_id 的長相
    # 來決定查哪張表。
    'us_gap': {
        'label': '美股開盤跳空預測',
        'workspace': _p('UnifiedModel', 'saved_models', 'us_gap.joblib'),
        'target_kind': 'us_gap',
        'horizon_days': 1,
        'logs_ledger': True,
    },
}

# LSTM：每個模型各自成為一個類型，artifact 是整個目錄（每檔股票一個 .keras）
# 名稱以 LSTM/config.py 的 MODEL_NAMES 為準（m09 是 technical、m10 是 ensemble）
LSTM_MODEL_NAMES = {
    'm01_vanilla': 'M01 Vanilla LSTM',
    'm02_stacked': 'M02 Stacked LSTM',
    'm03_bidirectional': 'M03 Bidirectional LSTM',
    'm04_attention': 'M04 LSTM + Attention',
    'm05_cnn_lstm': 'M05 CNN-LSTM',
    'm06_multifeature': 'M06 Multi-feature LSTM',
    'm07_seq2seq': 'M07 Seq2Seq LSTM',
    'm08_mc_dropout': 'M08 MC Dropout LSTM',
    'm09_technical': 'M09 LSTM + Technical',
    'm10_ensemble': 'M10 Ensemble',
}
for _k, _label in LSTM_MODEL_NAMES.items():
    MODEL_TYPES[f'lstm:{_k}'] = {
        'label': _label,
        'workspace': _p('LSTM', 'saved_models', _k),
        'target_kind': 'close',
        'horizon_days': 7,
        'logs_ledger': False,      # LSTM 推論走 :8001 代理，目前不落台帳
    }
    # 同一批模型套在美股上是另一個類型：模型檔相同，但台帳分開——
    # 台幣與美元的 MAE 混在同一個版本裡，線上指標就沒有意義。
    # target_kind 也分開（us_close），回填端才知道去 us_daily_prices 取價。
    MODEL_TYPES[f'lstm_us:{_k}'] = {
        'label': f'{_label}（美股）',
        'workspace': _p('LSTM', 'saved_models', _k),
        'target_kind': 'us_close',
        'horizon_days': 7,
        'logs_ledger': False,
    }


def describe(model_type: str) -> dict | None:
    return MODEL_TYPES.get(model_type)


def workspace_path(model_type: str) -> str | None:
    m = MODEL_TYPES.get(model_type)
    return m['workspace'] if m else None


def _snapshot_dir(model_type: str, version: int) -> str:
    """凍結快照的存放位置：與工作區同層的 _versions/<type>/v<N>/"""
    ws = MODEL_TYPES[model_type]['workspace']
    # 工作區可能是檔案（.../saved_models/x.joblib）或目錄（.../saved_models/m02_stacked）
    saved_root = os.path.dirname(ws)
    safe = model_type.replace(':', '_')
    return os.path.join(saved_root, '_versions', safe, f'v{version}')


# ── 資料庫存取（全部容錯）──────────────────────────────────────────────────────
def _conn():
    from db.connection import get_conn
    return get_conn()


def _fetchall(sql, params=None):
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or ())
                cols = [c[0] for c in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        logger.warning('[registry] 查詢失敗：%s', e)
        return None


def _execute(sql, params=None, returning=False):
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or ())
                out = None
                if returning:
                    row = cur.fetchone()
                    if row is not None:
                        cols = [c[0] for c in cur.description]
                        out = dict(zip(cols, row))
            conn.commit()
            return out
    except Exception as e:
        logger.warning('[registry] 寫入失敗：%s', e)
        return None


# ── 版本查詢與建立 ────────────────────────────────────────────────────────────
def get_versions(model_type: str = None) -> list:
    sql = 'SELECT * FROM model_versions'
    params = ()
    if model_type:
        sql += ' WHERE model_type = %s'
        params = (model_type,)
    sql += ' ORDER BY model_type, version DESC'
    return _fetchall(sql, params) or []


def ensure_candidate(model_type: str) -> dict | None:
    """
    取得該類型目前的 candidate；不存在則建立 v1（或接續最大版本號）。

    在推論或訓練時被動呼叫即可——不需要事先手動建立任何東西。
    """
    meta = MODEL_TYPES.get(model_type)
    if meta is None:
        logger.warning('[registry] 未知模型類型：%s', model_type)
        return None

    rows = _fetchall(
        "SELECT * FROM model_versions WHERE model_type = %s AND status = 'candidate'",
        (model_type,))
    if rows is None:
        return None            # 資料庫不可用
    if rows:
        return rows[0]

    nxt = _fetchall(
        'SELECT COALESCE(MAX(version), 0) + 1 AS v FROM model_versions WHERE model_type = %s',
        (model_type,))
    version = nxt[0]['v'] if nxt else 1
    return _execute(
        """INSERT INTO model_versions
             (model_type, version, status, artifact_path, target_kind, horizon_days)
           VALUES (%s, %s, 'candidate', %s, %s, %s)
           ON CONFLICT (model_type, version) DO NOTHING
           RETURNING *""",
        (model_type, version, meta['workspace'],
         meta['target_kind'], meta['horizon_days']),
        returning=True)


def register_training(model_type: str, trained_at=None, train_metrics: dict = None) -> dict | None:
    """
    訓練腳本在存檔後呼叫：把這次訓練記到目前的 candidate 上。

    **不會動到任何 frozen 版本**——那正是凍結的意義。
    """
    import json
    cand = ensure_candidate(model_type)
    if cand is None:
        return None

    # 若這個 candidate 已經累積了線上預測紀錄，代表重訓**換掉了產生那些紀錄的權重**。
    # 讓新權重繼承舊紀錄會直接汙染自動凍結的判定，所以改開一個新的 candidate，
    # 舊的退役、紀錄留在它名下。
    used = _fetchall(
        'SELECT COUNT(*) AS n FROM model_predictions WHERE model_version_id = %s',
        (cand['id'],))
    if used and used[0]['n'] > 0:
        meta = MODEL_TYPES[model_type]
        was_serving = bool(cand.get('is_serving'))
        _execute(
            """UPDATE model_versions
                  SET status = 'retired', is_serving = FALSE,
                      retired_at = CURRENT_TIMESTAMP,
                      freeze_note = COALESCE(freeze_note, '')
                                    || '權重已被重訓覆寫；預測紀錄保留供回溯，檔案已不存在。'
                WHERE id = %s""", (cand['id'],))
        nxt = _fetchall('SELECT COALESCE(MAX(version), 0) + 1 AS v '
                        'FROM model_versions WHERE model_type = %s', (model_type,))
        cand = _execute(
            """INSERT INTO model_versions
                 (model_type, version, status, is_serving, artifact_path,
                  target_kind, horizon_days)
               VALUES (%s, %s, 'candidate', %s, %s, %s, %s)
            RETURNING *""",
            (model_type, nxt[0]['v'] if nxt else 1, was_serving, meta['workspace'],
             meta['target_kind'], meta['horizon_days']),
            returning=True)
        if cand is None:
            return None
        logger.info('[registry] %s 重訓 → 舊 candidate 退役，新開 v%s',
                    model_type, cand['version'])

    return _execute(
        """UPDATE model_versions
              SET trained_at = COALESCE(%s, CURRENT_TIMESTAMP),
                  train_metrics = %s
            WHERE id = %s AND status = 'candidate'
        RETURNING *""",
        (trained_at, json.dumps(train_metrics) if train_metrics else None, cand['id']),
        returning=True)


def serving_version(model_type: str) -> dict | None:
    """推論端該載入哪一版：優先服役中的凍結版，否則 candidate。"""
    rows = _fetchall(
        'SELECT * FROM model_versions WHERE model_type = %s AND is_serving',
        (model_type,))
    if rows:
        return rows[0]
    if rows is None:
        return None            # 資料庫不可用，交由呼叫端回退
    return ensure_candidate(model_type)


def serving_path(model_type: str) -> str | None:
    """
    推論端載入路徑。資料庫不可用或檔案不存在時**回退到工作區路徑**，
    確保註冊機制永遠不會讓原本能跑的推論變成跑不動。
    """
    ws = workspace_path(model_type)
    v = serving_version(model_type)
    if v and v.get('artifact_path') and os.path.exists(v['artifact_path']):
        return v['artifact_path']
    if v and v.get('artifact_path') and not os.path.exists(v['artifact_path']):
        logger.warning('[registry] %s v%s 的檔案不存在（%s），回退工作區',
                       model_type, v.get('version'), v['artifact_path'])
    return ws


def loadable_versions(model_type: str) -> list:
    """
    推論端該跑哪幾版：服役版，加上與它不同的 candidate（影子評估）。

    **影子評估是自動凍結能運作的前提。** 台帳只會記下實際跑過的版本；
    若只跑服役版，candidate 永遠累積不到線上紀錄，也就永遠不可能達標——
    一旦凍結了第一版，整個機制就卡死。故 candidate 要跟著跑一次、
    結果只寫台帳不對外輸出。

    回傳 [(version_row_or_None, path, is_serving), ...]，第一筆必為對外服務的那版。
    資料庫不可用時回傳單一筆 (None, 工作區路徑, True)，維持原本行為。
    """
    ws = workspace_path(model_type)
    rows = _fetchall(
        'SELECT * FROM model_versions WHERE model_type = %s '
        "AND (is_serving OR status = 'candidate')", (model_type,))
    if rows is None:
        return [(None, ws, True)]

    serving = next((r for r in rows if r['is_serving']), None)
    cand = next((r for r in rows if r['status'] == 'candidate'), None)
    if serving is None:
        serving = cand or ensure_candidate(model_type)
    out = []
    if serving:
        p = serving['artifact_path']
        out.append((serving, p if os.path.exists(p) else ws, True))
    else:
        out.append((None, ws, True))
    if cand and serving and cand['id'] != serving['id'] and os.path.exists(cand['artifact_path']):
        out.append((cand, cand['artifact_path'], False))
    return out


# ── 凍結 ──────────────────────────────────────────────────────────────────────
def freeze(model_type: str, reason: str = 'manual', note: str = None,
           live_metrics: dict = None) -> dict:
    """
    把目前的 candidate 凍結為長期服役版本，並自動開出 v+1 candidate。

    步驟：
      1. 把工作區 artifact 複製成不可變快照
      2. candidate → frozen，artifact_path 改指快照
      3. 舊的服役版本卸下 is_serving（狀態仍保留為 frozen，可回溯、可切回）
      4. 新凍結版本 is_serving = true
      5. 建立 v+1 candidate，指回工作區——下次重訓就寫在那裡

    回傳 {'ok': bool, 'reason'|'frozen'|'next_candidate'}。
    """
    import json

    meta = MODEL_TYPES.get(model_type)
    if meta is None:
        return {'ok': False, 'reason': f'未知模型類型：{model_type}'}

    cand = ensure_candidate(model_type)
    if cand is None:
        return {'ok': False, 'reason': '資料庫不可用，無法凍結'}

    ws = meta['workspace']
    if not os.path.exists(ws):
        return {'ok': False,
                'reason': f'工作區尚無模型檔案（{ws}）——請先訓練再凍結'}

    # 1. 快照
    snap_dir = _snapshot_dir(model_type, cand['version'])
    try:
        if os.path.isdir(ws):
            if os.path.exists(snap_dir):
                shutil.rmtree(snap_dir)
            shutil.copytree(ws, snap_dir)
            snap_path = snap_dir
        else:
            os.makedirs(snap_dir, exist_ok=True)
            snap_path = os.path.join(snap_dir, os.path.basename(ws))
            shutil.copy2(ws, snap_path)
    except Exception as e:
        return {'ok': False, 'reason': f'快照複製失敗：{e}'}

    # 2~4. 狀態切換（同一交易內完成，避免出現兩個服役版本或零個 candidate）
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE model_versions SET is_serving = FALSE '
                    'WHERE model_type = %s AND is_serving', (model_type,))
                cur.execute(
                    """UPDATE model_versions
                          SET status = 'frozen', is_serving = TRUE,
                              artifact_path = %s,
                              frozen_at = CURRENT_TIMESTAMP,
                              freeze_reason = %s, freeze_note = %s,
                              live_metrics = %s
                        WHERE id = %s
                    RETURNING *""",
                    (snap_path, reason, note,
                     json.dumps(live_metrics) if live_metrics else None,
                     cand['id']))
                cols = [c[0] for c in cur.description]
                frozen = dict(zip(cols, cur.fetchone()))

                # 5. 開出下一版 candidate
                cur.execute(
                    'SELECT COALESCE(MAX(version), 0) + 1 FROM model_versions '
                    'WHERE model_type = %s', (model_type,))
                nxt_version = cur.fetchone()[0]
                cur.execute(
                    """INSERT INTO model_versions
                         (model_type, version, status, artifact_path,
                          target_kind, horizon_days)
                       VALUES (%s, %s, 'candidate', %s, %s, %s)
                    RETURNING *""",
                    (model_type, nxt_version, ws,
                     meta['target_kind'], meta['horizon_days']))
                cols = [c[0] for c in cur.description]
                nxt = dict(zip(cols, cur.fetchone()))
            conn.commit()
    except Exception as e:
        return {'ok': False, 'reason': f'狀態切換失敗：{e}'}

    logger.info('[registry] %s v%s 已凍結（%s），新 candidate v%s',
                model_type, frozen['version'], reason, nxt['version'])
    return {'ok': True, 'frozen': frozen, 'next_candidate': nxt}


def set_serving(version_id: int) -> dict:
    """把服役版本切換到指定的凍結版本（candidate 不可指定為長期服役版）。"""
    rows = _fetchall('SELECT * FROM model_versions WHERE id = %s', (version_id,))
    if not rows:
        return {'ok': False, 'reason': '找不到此版本'}
    v = rows[0]
    if v['status'] == 'candidate':
        return {'ok': False,
                'reason': 'candidate 會被下次重訓覆寫，不能指定為長期服役版；請先凍結'}
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute('UPDATE model_versions SET is_serving = FALSE '
                            'WHERE model_type = %s AND is_serving', (v['model_type'],))
                cur.execute("UPDATE model_versions "
                            "SET is_serving = TRUE, status = 'frozen', retired_at = NULL "
                            "WHERE id = %s", (version_id,))
            conn.commit()
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'reason': str(e)}


def retire(version_id: int) -> dict:
    """把一個凍結版本退役（檔案保留）。若它正在服役，退役後回退到 candidate。"""
    res = _execute(
        """UPDATE model_versions
              SET status = 'retired', is_serving = FALSE,
                  retired_at = CURRENT_TIMESTAMP
            WHERE id = %s AND status <> 'candidate'
        RETURNING *""", (version_id,), returning=True)
    if res is None:
        return {'ok': False, 'reason': '退役失敗（candidate 不可退役）'}
    return {'ok': True, 'version': res}


# ── 預測台帳 ──────────────────────────────────────────────────────────────────
def estimate_target_date(base_date, trading_days: int):
    """
    由基準日推估第 N 個交易日的日曆日期（只跳過週末，不含國定假日）。

    這只是台帳寫入當下的暫記值——真正的目標日在 `resolve_predictions.py`
    回填時會依資料庫裡的**真實交易日曆**修正。所以這裡不需要準確的假日表，
    也不該為此再維護一份行事曆。
    """
    from datetime import date, datetime, timedelta
    if isinstance(base_date, str):
        base_date = datetime.strptime(base_date[:10], '%Y-%m-%d').date()
    elif isinstance(base_date, datetime):
        base_date = base_date.date()
    elif not isinstance(base_date, date):
        base_date = date.fromisoformat(str(base_date)[:10])

    d, left = base_date, max(int(trading_days), 1)
    while left > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            left -= 1
    return d



def log_predictions(model_type: str, rows: list, version_id: int = None) -> int:
    """
    把一批預測寫入台帳，供日後與實際值比對。

    rows 每筆需含：stock_id、predicted_on、target_date、predicted_value
    選填：ref_value、baseline_value、ci_low、ci_high、horizon_days

    **baseline_value 請務必填。** 沒有同時記下天真基準的預測，
    事後就只能拿模型跟自己比——本專案已經有三次教訓證明那毫無意義。

    寫入失敗只記 warning：留紀錄是附帶效果，不能拖垮預測本身。
    """
    if not rows:
        return 0
    if version_id is None:
        v = serving_version(model_type)
        if v is None:
            return 0
        version_id = v['id']
    meta = MODEL_TYPES.get(model_type, {})
    kind = meta.get('target_kind', 'close')
    horizon = meta.get('horizon_days')

    values = [
        (version_id, r['stock_id'], kind, r['predicted_on'], r['target_date'],
         r.get('horizon_days', horizon), r.get('ref_value'), r['predicted_value'],
         r.get('baseline_value'), r.get('ci_low'), r.get('ci_high'))
        for r in rows
    ]
    try:
        from psycopg2.extras import execute_values
        with _conn() as conn:
            with conn.cursor() as cur:
                execute_values(cur, """
                    INSERT INTO model_predictions
                      (model_version_id, stock_id, target_kind, predicted_on,
                       target_date, horizon_days, ref_value, predicted_value,
                       baseline_value, ci_low, ci_high)
                    VALUES %s
                    ON CONFLICT (model_version_id, stock_id, target_kind,
                                 predicted_on, horizon_days)
                    DO UPDATE SET predicted_value = EXCLUDED.predicted_value,
                                  baseline_value  = EXCLUDED.baseline_value,
                                  ref_value       = EXCLUDED.ref_value,
                                  ci_low          = EXCLUDED.ci_low,
                                  ci_high         = EXCLUDED.ci_high,
                                  target_date     = EXCLUDED.target_date
                """, values)
            conn.commit()
        return len(values)
    except Exception as e:
        logger.warning('[registry] 台帳寫入失敗（%s）：%s', model_type, e)
        return 0
