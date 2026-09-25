"""
NewsModels 設定（Iteration 40）：新聞 + 股價 → 隔日／三日走勢的多模型實驗

執行環境：NewsModels/venv（torch CUDA、sentence-transformers、jieba、xgboost、lightgbm）。
資料庫連線沿用 Crawler/config.py。
"""
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.abspath(__file__))
CRAWLER = os.path.join(os.path.dirname(ROOT), 'Crawler')
if CRAWLER not in sys.path:
    sys.path.insert(0, CRAWLER)

DATA_DIR = os.path.join(ROOT, 'data')
RESULT_DIR = os.path.join(ROOT, 'results')
LOG_DIR = os.path.join(ROOT, 'logs')
REPORT_MD = os.path.join(os.path.dirname(ROOT), 'AI', 'Doc', 'NewsModels.md')
for d in (DATA_DIR, RESULT_DIR, LOG_DIR):
    os.makedirs(d, exist_ok=True)

NEWS_SINCE = date(2023, 8, 1)          # 新聞起點（鉅亨 API 回填自 2023-09，前面留一個月給注意力基準）
PRICE_SINCE = date(2023, 1, 1)         # 價格起點（動能與波動特徵要往前 60 日）
SAMPLE_SINCE = date(2023, 10, 1)       # 樣本起點
TEST_QUARTERS = ['2024Q3', '2024Q4', '2025Q1', '2025Q2', '2025Q3', '2025Q4', '2026Q1', '2026Q2', '2026Q3']
GAP_DAYS = 5                           # 訓練集與測試季之間空 5 個交易日，避免 3／5 日標籤洩漏
SEQ_LEN = 10                           # 序列模型回看天數
MAX_NEWS_PER_DAY = 12                  # HAN 每日最多取幾則（依 tier、長度排序）
MAX_TAGS = 10                          # 一則新聞標到超過 10 檔（盤勢綜述）就不當個股新聞
EMB_MODEL = 'paraphrase-multilingual-MiniLM-L12-v2'   # 384 維，支援中文，2021 年訓練（前視偏誤最小的選擇）
SENT_MODEL = 'bardsai/finance-sentiment-zh-base'      # 中文財經情緒（可選；下載失敗就跳過）
SEED = 42
