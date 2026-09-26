"""
全域設定檔

密碼與金鑰從 repo 根目錄的 .env 讀（見 .env.example），不寫在這個檔案裡——它會進公開的 repo。
"""
import os
from pathlib import Path


def _load_env(path: Path) -> None:
    """讀 .env（KEY=VALUE，# 註解）；不覆蓋已存在的環境變數。不依賴 python-dotenv。"""
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


_load_env(Path(__file__).resolve().parent.parent / '.env')

# ── 爬蟲延遲 (秒) ──────────────────────────────────────────────────────────────
DELAY_MIN = 1.5
DELAY_MAX = 4.0

# ── 請求逾時 (秒) ──────────────────────────────────────────────────────────────
REQUEST_TIMEOUT = 15

# ── 最大重試次數 ───────────────────────────────────────────────────────────────
MAX_RETRIES = 3

# ── TWSE API ───────────────────────────────────────────────────────────────────
TWSE_API = {
    # 個股每日行情：需傳入 date (YYYYMMDD) 與 stockNo
    "stock_day": "https://www.twse.com.tw/exchangeReport/STOCK_DAY",
    # 三大法人每日買賣超：需傳入 date (YYYYMMDD)
    "chip": "https://www.twse.com.tw/fund/T86",
    # 上市股票清單
    "stock_list": "https://www.twse.com.tw/exchangeReport/BWIBBU_d",
}

# ── PostgreSQL 連線設定 ────────────────────────────────────────────────────────
# CRAWLER_TEST_DB：只給 tests/ 用——設了就改連這個資料庫（其餘連線參數不變），正式執行不會設。
DB = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", "5432")),
    "dbname": os.environ.get("CRAWLER_TEST_DB") or os.environ.get("DB_NAME", "Stock"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),      # 只從 .env 來
}

# ── 排程設定 ───────────────────────────────────────────────────────────────────
SCHEDULE = {
    # 股價爬蟲：每日 18:00（台股收盤後）執行
    "stock_cron": {"hour": 18, "minute": 0},
    # 新聞爬蟲 + 情緒特徵：每小時第 5 分執行
    "news_cron": {"minute": 5},
    # 三模型加權投票：每日 20:00 執行
    "vote_cron": {"hour": 20, "minute": 0},
}

# ── FinMind API 設定 ────────────────────────────────────────────────────────
FINMIND = {
    # API Token：可於 https://finmindtrade.com/ 免費申請，填在 .env 的 FINMIND_TOKEN
    # 匿名模式可使用但有速率限制（每小時 30 次）
    # 填入 token 後可提高至每小時 600 次
    "token": os.environ.get("FINMIND_TOKEN", ""),
}


def validate() -> None:
    """設定檢查：密碼沒填就明講，不要等到 psycopg2 吐一串英文。目前沒有人在啟動時呼叫，供測試與手動檢查。"""
    if not DB["password"]:
        raise ValueError("DB_PASSWORD 未設定：請在 repo 根目錄的 .env 填 DB_PASSWORD（見 .env.example）")
