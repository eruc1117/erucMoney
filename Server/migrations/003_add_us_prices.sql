-- Iteration 14：美股日線資料表
--
-- 為何獨立成表而非併入 stock_daily_prices：
--   兩個市場的交易日曆不同（美股有台股沒有的假期，反之亦然）。
--   若混在同一張表，橫斷面特徵（同日 N 檔之間的百分位排名）
--   會把不同市場、不同時區的資料放在同一天比較，直接汙染台股面板。
--
-- adj_close 為還原除權息後的收盤價，計算報酬率時必須用它；
-- close 保留原始值供顯示與對帳。

CREATE TABLE IF NOT EXISTS us_daily_prices (
    ticker      VARCHAR(12)  NOT NULL,
    trade_date  DATE         NOT NULL,
    open_price  NUMERIC(14, 4),
    high_price  NUMERIC(14, 4),
    low_price   NUMERIC(14, 4),
    close_price NUMERIC(14, 4),
    adj_close   NUMERIC(14, 4),
    volume      BIGINT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_us_daily_prices_date ON us_daily_prices (trade_date);

-- 美股標的清單（可標記用途，便於日後擴充）
CREATE TABLE IF NOT EXISTS us_tickers (
    ticker      VARCHAR(12) PRIMARY KEY,
    name        VARCHAR(100),
    category    VARCHAR(30),      -- index / semiconductor / bigtech / tw_adr
    is_tracking BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
