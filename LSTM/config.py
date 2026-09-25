"""
LSTM 模型訓練全域設定
"""
import os
from pathlib import Path

# ── 根目錄 ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent


def _load_env(path: Path) -> None:
    """讀 repo 根目錄的 .env（KEY=VALUE，# 註解）；不覆蓋已存在的環境變數。不依賴 python-dotenv。"""
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


_load_env(BASE_DIR.parent / '.env')

# ── 輸出目錄 ───────────────────────────────────────────────────────────────────
RESULTS_DIR    = BASE_DIR / "results"
SAVED_DIR      = BASE_DIR / "saved_models"
REPORT_DIR     = BASE_DIR / "report"

# ── PostgreSQL 連線 ────────────────────────────────────────────────────────────
DB = {
    "host":     os.environ.get("DB_HOST", "localhost"),
    "port":     int(os.environ.get("DB_PORT", "5432")),
    "dbname":   os.environ.get("DB_NAME", "Stock"),
    "user":     os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),      # 只從 .env 來，不寫在程式裡
}

# ── 資料切割比例 ───────────────────────────────────────────────────────────────
TRAIN_RATIO = 0.70   # 70%
VAL_RATIO   = 0.15   # 15%
TEST_RATIO  = 0.15   # 15%

# ── 序列設定 ───────────────────────────────────────────────────────────────────
LOOKBACK    = 20     # 以過去 20 個交易日預測明日
FORECAST_STEPS = 5   # Seq2Seq 預測未來 5 天

# ── 訓練超參數 ─────────────────────────────────────────────────────────────────
EPOCHS      = 100
BATCH_SIZE  = 32
PATIENCE    = 15     # Early stopping patience
LR          = 1e-3

# ── MC Dropout 推論次數 ────────────────────────────────────────────────────────
MC_SAMPLES  = 50

# ── 集成模型權重（M10 Ensemble）─────────────────────────────────────────────────
ENSEMBLE_WEIGHTS = {
    "m01_vanilla":       0.25,
    "m02_stacked":       0.45,
    "m03_bidirectional": 0.30,
}

# ── 模型名稱對照（用於報告）──────────────────────────────────────────────────────
MODEL_NAMES = {
    "m01_vanilla":       "M01 Vanilla LSTM",
    "m02_stacked":       "M02 Stacked LSTM",
    "m03_bidirectional": "M03 Bidirectional LSTM",
    "m04_attention":     "M04 LSTM + Attention",
    "m05_cnn_lstm":      "M05 CNN-LSTM",
    "m06_multifeature":  "M06 Multi-feature LSTM",
    "m07_seq2seq":       "M07 Seq2Seq LSTM",
    "m08_mc_dropout":    "M08 MC Dropout LSTM",
    "m09_technical":     "M09 LSTM + Technical",
    "m10_ensemble":      "M10 Ensemble",
}
