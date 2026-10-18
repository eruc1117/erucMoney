-- Iteration 81：全市場融資融券與借券賣出（Papers.md P62、P65～P68 的資料前提；資料工作，不算 N）
--
-- 為什麼要新表：散戶融資（反向，Ting, Lu & Chou 2018）、融券與法人借券放空（Hu, Huang & Liao 2009；Lin, Ho & Ko 2023；TEJ SIR）
-- 是和動能、價值、法人買賣超都不同的籌碼面訊號，庫裡沒有。來源走交易所官方檔：
--   證交所 marginTrading/MI_MARGN（融資融券彙總，單位張）＋ marginTrading/TWT93U（信用額度總量管制餘額表：融券＋借券賣出，單位股）；
--   櫃買 margin/balance（融資融券餘額，張）＋ margin/sbl（信用額度總量管制餘額表，股）。
-- 一天四次呼叫拿全市場，不吃 FinMind 額度——和 market_daily_prices、market_institutional_daily、market_valuation_daily 同一條路線。
-- 單位一律存「股」（張 × 1,000）。兩張表都有「融券餘額」，寫入前逐列對位檢查（不等的列超過 1% 就當格式變了擋下）。
-- 借券表沒列的股票（沒有信用交易資格）借券欄為 NULL、不是 0。
-- 誰寫：Crawler/margin_data.py（回補與每日 18:39 排程 job_margin_daily）。誰讀：之後的 portfolio_signal 放空／融資訊號。

CREATE TABLE IF NOT EXISTS market_margin_daily (
    stock_id        VARCHAR(10) NOT NULL,
    trade_date      DATE        NOT NULL,
    margin_buy      BIGINT,                      -- 融資買進（股）
    margin_sell     BIGINT,                      -- 融資賣出（股）
    margin_balance  BIGINT      NOT NULL,        -- 融資餘額（股）
    short_buy       BIGINT,                      -- 融券買進（回補，股）
    short_sell      BIGINT,                      -- 融券賣出（股）
    short_balance   BIGINT      NOT NULL,        -- 融券餘額（股）
    sbl_sell        BIGINT,                      -- 借券賣出當日賣出（股）
    sbl_balance     BIGINT,                      -- 借券賣出餘額（股）
    source          VARCHAR(10) NOT NULL,        -- twse / tpex
    fetched_at      TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (stock_id, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_market_margin_date ON market_margin_daily (trade_date);
