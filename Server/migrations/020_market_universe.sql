-- Iteration 48：全市場股票池與日線（「打敗大盤」計畫階段 1）
--
-- 為什麼另開兩張表、不塞進 stock_info / stock_daily_prices：
--   那兩張表被 LSTM data_loader、rebuild_adj_close、sync_stock_info、排程新鮮度檢查當成
--   「追蹤股清單」在用（AI/Doc/DB.md 2.8 節的教訓）。全市場約 1,800 檔塞進去，LSTM 會多訓練
--   一千多檔、新鮮度檢查天天報落後。月調倉選股只讀這兩張新表，舊表與舊流程完全不動。
--
-- market_universe：上市櫃普通股（4 碼、不以 0 開頭；ETF、特別股、TDR、興櫃不收），
--   含已下市者（delisted_date 非 NULL）——回測沒有下市股就是存活者偏差。
-- market_daily_prices：2018 起的日線，欄位與 stock_daily_prices 對齊，另有 adj_close
--   （還原除權息與減資，事件表沿用 stock_dividend_result / stock_capital_reduction）與 source。
--   報酬一律用 adj_close，close 只供顯示。

CREATE TABLE IF NOT EXISTS market_universe (
    stock_id        VARCHAR(12) PRIMARY KEY,
    stock_name      VARCHAR(50),
    market_type     VARCHAR(10),                 -- twse / tpex；只在下市表出現的股票為 NULL
    industry_type   VARCHAR(50),
    listing_date    DATE,
    delisted_date   DATE,                        -- NULL = 仍在市
    security_type   VARCHAR(10) NOT NULL DEFAULT 'stock',
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_market_universe_delisted ON market_universe (delisted_date);

CREATE TABLE IF NOT EXISTS market_daily_prices (
    stock_id            VARCHAR(12)    NOT NULL,
    trade_date          DATE           NOT NULL,
    open_price          NUMERIC(12, 4),
    high_price          NUMERIC(12, 4),
    low_price           NUMERIC(12, 4),
    close_price         NUMERIC(12, 4),
    volume              BIGINT,                  -- 成交股數
    turnover_value      NUMERIC(20, 2),          -- 成交金額（元）
    transaction_count   INTEGER,
    change_value        NUMERIC(12, 4),          -- 漲跌（元）；除權息日交易所標 X，為 NULL
    adj_close           NUMERIC(14, 4),          -- 還原價；計算報酬一律用本欄
    source              VARCHAR(10),             -- finmind / twse / tpex
    fetched_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (stock_id, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_market_prices_date ON market_daily_prices (trade_date);

COMMENT ON TABLE market_universe IS '全市場上市櫃普通股（含已下市），Crawler/market_universe.py 同步';
COMMENT ON TABLE market_daily_prices IS '全市場日線 2018 起，Crawler/market_data.py 回補與每日更新；報酬用 adj_close';
