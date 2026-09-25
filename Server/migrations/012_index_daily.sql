-- Iteration 29：亞洲主要指數（韓股 KOSPI、日股 Nikkei 225）
--
-- 為何是這兩個：**它們比台股早一小時開盤**。
--   韓國 KRX  09:00 KST = 08:00 台北　收盤 15:30 KST = 14:30 台北
--   日本 TSE  09:00 JST = 08:00 台北　收盤 15:00 JST = 14:00 台北
--   台灣 TWSE 09:00 台北　　　　　　 收盤 13:30 台北
--
-- 時序是這份資料唯一的陷阱，而且方向相反於直覺：
--
--   當日**開盤價**  08:00 台北就知道 → 預測台股當日開盤跳空**可用**
--   當日**收盤價**  14:00~14:30 台北 → 在台股開盤（09:00）**之後**，
--                   甚至在台股收盤（13:30）之後 → 預測當日任何事都**不可用**
--   前一日收盤價    前一日 14:00~14:30 → 可用，且它比台股前一日收盤（13:30）
--                   多含約一小時的資訊
--
-- 用錯就是未來資訊洩漏，而且症狀是「模型好得不像話」。
-- 特徵模組 `intl_features.py` 只會產出符合上述規則的欄位。

CREATE TABLE IF NOT EXISTS index_daily_prices (
    symbol      VARCHAR(16) NOT NULL,     -- ^KS11 / ^N225
    trade_date  DATE        NOT NULL,
    open_price  NUMERIC(16, 4),
    high_price  NUMERIC(16, 4),
    low_price   NUMERIC(16, 4),
    close_price NUMERIC(16, 4),
    volume      BIGINT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_index_daily_date ON index_daily_prices (trade_date);
