"""
LSTM 預測 FastAPI 伺服器（port 8001）
─────────────────────────────────────
提供前端所需的預測 API，供 Node.js Server proxy 使用。

啟動方式：
    cd LSTM
    venv\\Scripts\\activate
    python serve.py
    # 或：
    uvicorn serve:app --host 0.0.0.0 --port 8001 --reload

模型對應：
    lstm    → m02_stacked        (3 層堆疊 LSTM)
    prophet → m09_technical      (LSTM + 20 種技術指標)
    gru     → m03_bidirectional  (雙向 LSTM)
"""
import os
import sys
import json
import logging
import subprocess
import threading
from datetime import date, timedelta
from pathlib import Path

# ── 讓 serve.py 能 import 同目錄的模組 ──────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

import warnings
warnings.filterwarnings("ignore")

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import numpy as np

from config import LOOKBACK, RESULTS_DIR, SAVED_DIR, MODEL_NAMES
from data_loader import load_prices, load_us_prices

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── 支援的模型清單（m07/m10 需另行訓練，暫不包含在 cross-stock 流程中）────
SUPPORTED_MODELS = {
    "m01_vanilla", "m02_stacked", "m03_bidirectional",
    "m04_attention", "m05_cnn_lstm", "m06_multifeature",
    "m07_seq2seq", "m08_mc_dropout", "m09_technical", "m10_ensemble",
}
# 向下相容舊別名（lstm / prophet / gru）
_ALIAS = {
    "lstm":    "m02_stacked",
    "prophet": "m09_technical",
    "gru":     "m03_bidirectional",
}
CROSS_SAVED = SAVED_DIR / "cross_stock"
CROSS_RESULTS = RESULTS_DIR / "cross_stock"

app = FastAPI(title="LSTM Prediction API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# ── 模型快取（避免每次請求重新載入）────────────────────────────────────────
_model_cache: dict = {}
_cache_lock = threading.Lock()


def _custom_objects() -> dict:
    """
    自訂 Keras 層的對照表。

    m04_attention 使用自訂層 BahdanauAttention；不傳 custom_objects 時
    `load_model` 會拋 "Could not locate class 'BahdanauAttention'" 而回 500。
    `/health` 只檢查檔案存在與否，因此仍把 m04 列為可用，錯誤直到前端呼叫才浮現。
    """
    objs = {}
    try:
        from models.m04_attention import BahdanauAttention
        objs["BahdanauAttention"] = BahdanauAttention
    except Exception as e:      # 缺模組不應讓其他模型一起掛掉
        logger.warning("載入自訂層 BahdanauAttention 失敗：%s", e)
    return objs


# 載入失敗的模型與原因（供 /health 誠實回報，避免再度謊報可用）
_model_errors: dict = {}


def _get_model(model_key: str):
    """載入或從快取取得模型；載入失敗回 None 並記錄原因。"""
    import tensorflow as tf
    with _cache_lock:
        if model_key in _model_cache:
            return _model_cache[model_key]
        if model_key in _model_errors:
            return None

        path = CROSS_SAVED / f"{model_key}.keras"
        if not path.exists():
            _model_errors[model_key] = "模型檔不存在（尚未訓練）"
            return None

        logger.info("載入模型：%s", path)
        try:
            _model_cache[model_key] = tf.keras.models.load_model(
                str(path), custom_objects=_custom_objects(),
            )
        except Exception as e:
            _model_errors[model_key] = f"{type(e).__name__}: {e}"
            logger.error("模型 %s 載入失敗：%s", model_key, e)
            return None
        return _model_cache[model_key]


def _load_mape(model_key: str, stock_id: str) -> float:
    """嘗試從 metrics.json 取得 MAPE，做為信賴區間基準"""
    # 優先取個股跨股票結果
    path = CROSS_RESULTS / model_key / "metrics.json"
    if path.exists():
        try:
            with open(path) as f:
                data = json.load(f)
            # 先找個股，再找整體
            for item in data.get("per_stock", []):
                if item.get("stock_id") == stock_id:
                    return float(item.get("MAPE", 3.0))
            return float(data.get("overall", {}).get("MAPE", 3.0))
        except Exception:
            pass
    return 3.0   # 預設 3%


def _zscore_normalize(window: np.ndarray, eps: float = 1e-8):
    mean = window.mean()
    std  = window.std() + eps
    return (window - mean) / std, mean, std


def _predict_rolling(model, prices: np.ndarray, days: int):
    """
    滾動預測未來 days 天，回傳 (predictions, means, stds)。

    支援兩種輸出形狀：
      單步模型 (1, 1)        每次前進一天，把預測值接回輸入視窗
      Seq2Seq  (1, steps, 1) 一次取得多天，不足時再滾動下一批
        —— M07 屬於後者，用單步邏輯只會取到第 1 步而浪費其多步能力。
    """
    buf = list(prices[-LOOKBACK:].astype(float))
    preds, means, stds = [], [], []
    while len(preds) < days:
        window = np.array(buf[-LOOKBACK:])
        x_norm, mean, std = _zscore_normalize(window)
        x_in = x_norm.reshape(1, LOOKBACK, 1).astype("float32")
        out = model.predict(x_in, verbose=0)

        step_vals = (out[0, :, 0] if out.ndim == 3 else np.atleast_1d(out[0]).ravel()[:1])
        for y_norm in step_vals:
            if len(preds) >= days:
                break
            price = float(y_norm) * std + mean
            preds.append(price)
            means.append(mean)
            stds.append(std)
            buf.append(price)
    return preds, means, stds


def _ensemble_config() -> dict | None:
    """讀取 M10 的權重設定（train_cross.py --models m10_ensemble 產生）。"""
    path = CROSS_SAVED / "m10_ensemble.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("M10 權重設定讀取失敗：%s", e)
        return None


def _predict_ensemble(prices: np.ndarray, days: int):
    """
    M10 集成：逐日以各基礎模型預測後加權平均，再把結果接回輸入視窗。

    M10 沒有 .keras 模型檔——它本來就不是可訓練的網路，而是組合方法。
    權重由各基礎模型測試集 MAE 的反比決定（見 train_cross.build_ensemble）。
    """
    cfg = _ensemble_config()
    if cfg is None:
        return None, "尚未建立集成權重，請執行 python train_cross.py --models m10_ensemble"

    models, weights = {}, {}
    for key, w in cfg["weights"].items():
        m = _get_model(key)
        if m is not None:
            models[key], weights[key] = m, w
    if not models:
        return None, "基礎模型皆無法載入，M10 無法推論"

    total_w = sum(weights.values())
    buf = list(prices[-LOOKBACK:].astype(float))
    preds, means, stds = [], [], []
    for _ in range(days):
        window = np.array(buf[-LOOKBACK:])
        x_norm, mean, std = _zscore_normalize(window)
        x_in = x_norm.reshape(1, LOOKBACK, 1).astype("float32")

        blended = 0.0
        for key, m in models.items():
            out = m.predict(x_in, verbose=0)
            val = float(out[0, 0, 0]) if out.ndim == 3 else float(np.atleast_1d(out[0]).ravel()[0])
            blended += val * weights[key]
        y_norm = blended / total_w

        price = y_norm * std + mean
        preds.append(price)
        means.append(mean)
        stds.append(std)
        buf.append(price)
    return (preds, means, stds), None


def _next_trading_dates(n: int) -> list[str]:
    """產生未來 n 個日期（跳過週末）"""
    dates, d = [], date.today()
    while len(dates) < n:
        d += timedelta(days=1)
        if d.weekday() < 5:   # 0=Mon … 4=Fri
            dates.append(d.isoformat())
    return dates


def _next_us_session_dates(n: int, last_data: date) -> list[str]:
    """
    美股：產生未來 n 個交易日（以美東的場次日期表示）。

    與台股不同，這裡不能直接從「明天」開始算。台北時間 D 日白天，
    美股 D 日那一場（21:30 開盤）還沒開始，最新的收盤是 D−1——
    所以 D 日本身就是第一個可預測的場次，跳過它等於白丟一天。
    另一方面也不能從最後一筆資料的隔天開始：資料落後時那會產生
    已經開過的場次，存進比對表立刻就「到期」，看起來像是預測，其實是回顧。

    規則：第一個場次＝max(最後一筆資料的下一個平日, 今天（平日）)。
    美國國定假日與台股一樣不處理，比對時以真實交易日對齊（resolve_predictions）。
    """
    def next_weekday(d):
        d += timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d

    today = date.today()
    first = today if today.weekday() < 5 else next_weekday(today)
    after_data = next_weekday(last_data)
    d = max(first, after_data)
    dates = [d.isoformat()]
    while len(dates) < n:
        d = next_weekday(d)
        dates.append(d.isoformat())
    return dates


# ── GET /model/predict ──────────────────────────────────────────────────────
def _normalise_stock_id(raw: str) -> str:
    """
    去除前後空白並把全形數字轉半形。

    股票代號常常是複製貼上進來的，尾隨一個空白就會讓查詢變成 0 筆，
    而錯誤訊息只會說「資料不足」——那是最難查的一種錯誤：
    看起來像資料問題，其實是輸入問題。
    """
    if not raw:
        return raw
    s = str(raw).strip()
    return s.translate(str.maketrans('０１２３４５６７８９', '0123456789'))


def _shortage_detail(stock_id: str, df, market: str = "tw") -> str:
    """資料不足時，順便告訴使用者資料庫裡到底有沒有這檔。"""
    have = 0 if df is None else len(df)
    msg = f"股票 {stock_id} 資料不足（需 {LOOKBACK} 筆，目前 {have} 筆）"
    if market == "us":
        # 美股標的固定 12 檔，不是「沒抓過」就是「代號不在清單裡」
        return msg + "；美股行情由排程 06:10／19:10 更新，可先在頁面上補齊外生資料"
    if have == 0:
        try:
            import psycopg2
            from config import DB
            with psycopg2.connect(host=DB["host"], port=DB["port"], dbname=DB["dbname"],
                                  user=DB["user"], password=DB["password"]) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT count(*) FROM stock_daily_prices WHERE stock_id = %s",
                                (stock_id.strip(),))
                    trimmed = cur.fetchone()[0]
            if trimmed > 0:
                msg += f"——但去除空白後的「{stock_id.strip()}」有 {trimmed} 筆，代號可能夾帶了空白字元"
            else:
                msg += "；資料庫中沒有這檔的行情，可先執行爬蟲補足資料"
        except Exception:
            msg += "；資料庫中沒有這檔的行情，可先執行爬蟲補足資料"
    return msg


@app.get("/model/predict")
def get_prediction(
    stock_id: str = Query(..., description="股票代碼"),
    model:    str = Query("m02_stacked", description="m01_vanilla ~ m10_ensemble"),
    days:     int = Query(7, ge=1, le=30),
    market:   str = Query("tw", description="tw（stock_daily_prices）或 us（us_daily_prices）"),
):
    # 代號先正規化：貼上時夾帶的空白會讓查詢變成 0 筆，
    # 而錯誤訊息只會說「資料不足」，完全看不出是輸入被污染
    stock_id = _normalise_stock_id(stock_id)
    if not stock_id:
        raise HTTPException(400, "stock_id 為必填")
    market = (market or "tw").lower()
    if market not in ("tw", "us"):
        raise HTTPException(400, f"不支援的市場：{market}，可用：tw、us")
    if market == "us":
        stock_id = stock_id.upper()

    # 支援舊別名 lstm / prophet / gru
    model_key = _ALIAS.get(model, model)
    if model_key not in SUPPORTED_MODELS:
        raise HTTPException(400, f"不支援的模型：{model}，可用：{sorted(SUPPORTED_MODELS)}")

    # M10 沒有模型檔（它是組合方法），走專屬路徑
    is_ensemble = model_key == "m10_ensemble"
    m = None
    if not is_ensemble:
        m = _get_model(model_key)
        if m is None:
            reason = _model_errors.get(model_key, "未知原因")
            if "不存在" in reason:
                raise HTTPException(503,
                    f"模型 {model_key} 尚未訓練，請先執行 python train_cross.py")
            raise HTTPException(503, f"模型 {model_key} 載入失敗：{reason}")

    # 從 DB 取近期收盤價（美股走另一張表，欄位語意相同）
    try:
        df = load_us_prices(stock_id) if market == "us" else load_prices(stock_id)
    except Exception as e:
        raise HTTPException(500, f"資料庫錯誤：{e}")

    if df is None or len(df) < LOOKBACK:
        # 分辨「這檔真的沒資料」與「查詢條件有問題」。
        # 實際踩過：股票代號夾帶一個尾隨空白，'3231 ' 在資料庫是 0 筆而
        # '3231' 有 5,654 筆，錯誤訊息卻只說「資料不足」，看不出是代號被污染。
        raise HTTPException(404, _shortage_detail(stock_id, df, market))

    prices = df["close_price"].values

    # 滾動預測
    if is_ensemble:
        out, err = _predict_ensemble(prices, days)
        if out is None:
            raise HTTPException(503, f"M10 集成無法推論：{err}")
        preds, _, _ = out
    else:
        preds, _, _ = _predict_rolling(m, prices, days)

    # 信賴區間（MAPE 為基，區間隨步數擴大）
    mape   = _load_mape(model_key, stock_id)
    base_σ = prices[-1] * (mape / 100)   # 第 1 天基準誤差

    dates = (_next_us_session_dates(days, df.index[-1].date()) if market == "us"
             else _next_trading_dates(days))
    result = []
    for i, (pred, d) in enumerate(zip(preds, dates), 1):
        σ = base_σ * (i ** 0.5)          # 隨步數擴大
        result.append({
            "date":            d,
            "predicted_close": round(float(pred),    2),
            "ci_low":          round(float(pred - 1.96 * σ), 2),
            "ci_high":         round(float(pred + 1.96 * σ), 2),
        })

    logger.info("預測完成 market=%s stock=%s model=%s days=%d", market, stock_id, model, days)
    return result


# ── POST /model/retrain ──────────────────────────────────────────────────────
_retrain_state = {"status": "idle", "stock_id": None, "message": ""}
_retrain_lock  = threading.Lock()


@app.post("/model/retrain")
def retrain(body: dict):
    stock_id = body.get("stock_id", "")
    with _retrain_lock:
        if _retrain_state["status"] == "running":
            return {"status": "already_running", "task_id": "retrain"}

        _retrain_state.update(status="running", stock_id=stock_id, message="訓練中...")

    def _run():
        try:
            cmd = [sys.executable, "train_cross.py"]
            if stock_id:
                cmd += ["--stocks", stock_id]
            result = subprocess.run(
                cmd,
                cwd=str(Path(__file__).parent),
                capture_output=True, text=True, timeout=3600,
            )
            # 清除模型快取，下次請求時重新載入
            with _cache_lock:
                _model_cache.clear()
            with _retrain_lock:
                if result.returncode == 0:
                    _retrain_state.update(status="done", message="重訓完成")
                else:
                    _retrain_state.update(status="error",
                                          message=result.stderr[-500:] or "未知錯誤")
        except subprocess.TimeoutExpired:
            with _retrain_lock:
                _retrain_state.update(status="error", message="訓練超時（>1h）")
        except Exception as e:
            with _retrain_lock:
                _retrain_state.update(status="error", message=str(e))

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "task_id": "retrain"}


@app.get("/model/retrain/status")
def retrain_status():
    with _retrain_lock:
        return dict(_retrain_state)


# ── 健康檢查 ──────────────────────────────────────────────────────────────
@app.get("/health")
def health(verify: bool = Query(False, description="true 時實際載入模型驗證可用性")):
    """
    預設只回報模型檔是否存在（快速）。

    注意：檔案存在 ≠ 可載入。m04_attention 曾因自訂層無法反序列化而
    「檔案在、health 說可用、一呼叫就 500」。要確認真的能用請帶 ?verify=true
    （會實際載入全部模型，首次呼叫較慢，之後走快取）。
    """
    on_disk = sorted(k for k in SUPPORTED_MODELS if (CROSS_SAVED / f"{k}.keras").exists())
    # M10 是組合方法而非網路，可用與否取決於權重設定檔是否存在
    ensemble_ready = _ensemble_config() is not None
    if ensemble_ready:
        on_disk = sorted(set(on_disk) | {"m10_ensemble"})

    resp = {"status": "ok", "available_models": on_disk,
            "missing_models": sorted(SUPPORTED_MODELS - set(on_disk)),
            "ensemble_ready": ensemble_ready}

    if verify:
        loadable, failed = [], {}
        for k in on_disk:
            if k == "m10_ensemble":
                loadable.append(k)      # 能進 on_disk 就代表權重設定已存在
                continue
            if _get_model(k) is not None:
                loadable.append(k)
            else:
                failed[k] = _model_errors.get(k, "未知原因")
        resp.update({"verified": True, "loadable_models": loadable,
                     "failed_models": failed})
    else:
        # 已知的載入失敗即使未 verify 也一併回報
        resp["failed_models"] = dict(_model_errors)
    return resp


if __name__ == "__main__":
    import uvicorn
    logger.info("啟動 LSTM 預測伺服器 http://0.0.0.0:8001")
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="warning")
