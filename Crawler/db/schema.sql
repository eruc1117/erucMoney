-- ============================================================
-- 初始化腳本：建立台股相關資料表
-- 對應 AI/Doc/DB.md 第 2 節設計
-- 執行方式：psql -U postgres -d money -f db/schema.sql
-- ============================================================

-- 個股基本資訊表
CREATE TABLE IF NOT EXISTS stock_info (
    stock_id        VARCHAR(10) PRIMARY KEY,
    stock_name      VARCHAR(50) NOT NULL,
    market_type     VARCHAR(10),
    industry_type   VARCHAR(50),
    listing_date    DATE,
    is_tracking     BOOLEAN DEFAULT TRUE,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 每日行情表
CREATE TABLE IF NOT EXISTS stock_daily_prices (
    stock_id            VARCHAR(10)    NOT NULL,
    trade_date          DATE           NOT NULL,
    open_price          NUMERIC(10, 2),
    high_price          NUMERIC(10, 2),
    low_price           NUMERIC(10, 2),
    close_price         NUMERIC(10, 2),
    volume              BIGINT,
    turnover_value      NUMERIC(18, 2),
    transaction_count   INT,
    change_value        NUMERIC(10, 2),
    change_rate         NUMERIC(6, 3),
    PRIMARY KEY (stock_id, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_price_date ON stock_daily_prices (trade_date DESC);

-- 三大法人籌碼表
CREATE TABLE IF NOT EXISTS stock_chip_analysis (
    stock_id                VARCHAR(10)   NOT NULL,
    trade_date              DATE          NOT NULL,
    foreign_investor_buy    BIGINT,
    investment_trust_buy    BIGINT,
    dealer_buy              BIGINT,
    total_net_buy           BIGINT,
    foreign_holding_ratio   NUMERIC(5, 2),
    PRIMARY KEY (stock_id, trade_date)
);

-- 外資持股統計（絕對持股，Iteration 35；來源 FinMind TaiwanStockShareholding）
-- 與 stock_chip_analysis 分表：那邊是每日買賣超，這邊是每日「手上有多少」。
CREATE TABLE IF NOT EXISTS stock_foreign_holding (
    stock_id                  VARCHAR(10)   NOT NULL,
    trade_date                DATE          NOT NULL,
    foreign_shares            BIGINT,          -- 外資持有股數（股）
    foreign_ratio             NUMERIC(6, 2),   -- 外資持股比例 (%)
    foreign_upper_limit_ratio NUMERIC(6, 2),   -- 外資投資上限 (%)
    shares_issued             BIGINT,          -- 已發行股數（股）
    PRIMARY KEY (stock_id, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_foreign_holding_date ON stock_foreign_holding (trade_date DESC);

-- 模型訓練整合視圖
CREATE OR REPLACE VIEW v_model_training_data AS
SELECT
    p.stock_id,
    p.trade_date,
    p.close_price,
    p.change_rate,
    c.total_net_buy
FROM stock_daily_prices p
LEFT JOIN stock_chip_analysis c
    ON p.stock_id = c.stock_id AND p.trade_date = c.trade_date;
