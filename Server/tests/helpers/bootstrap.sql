-- 測試資料庫的基底資料表。
-- 正式環境這些表由 Crawler（Crawler/db/schema.sql）與 app.init() 建立，migration 001/002/013/017 假設它們已存在；
-- 空的 Stock_test 要先有這些，migration 才跑得過。內容照抄正式 schema（欄位型別與主鍵一致）。

CREATE TABLE IF NOT EXISTS stock_info (
    stock_id        VARCHAR(10) PRIMARY KEY,
    stock_name      VARCHAR(50) NOT NULL,
    market_type     VARCHAR(10),
    industry_type   VARCHAR(50),
    listing_date    DATE,
    is_tracking     BOOLEAN DEFAULT TRUE,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

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

CREATE TABLE IF NOT EXISTS stock_foreign_holding (
    stock_id                  VARCHAR(10)   NOT NULL,
    trade_date                DATE          NOT NULL,
    foreign_shares            BIGINT,
    foreign_ratio             NUMERIC(6, 2),
    foreign_upper_limit_ratio NUMERIC(6, 2),
    shares_issued             BIGINT,
    PRIMARY KEY (stock_id, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_foreign_holding_date ON stock_foreign_holding (trade_date DESC);

-- 以下三張正式環境由 app.init() 建（但 migration 002/013/017 在 init 之前就會 ALTER 它們）
CREATE TABLE IF NOT EXISTS voting_results (
    id            SERIAL PRIMARY KEY,
    stock_id      VARCHAR(10)  NOT NULL,
    vote_date     DATE         NOT NULL,
    m1_signal     VARCHAR(4),
    m2_signal     VARCHAR(4),
    m3_signal     VARCHAR(4),
    final_signal  VARCHAR(4),
    score         FLOAT,
    weights       JSONB,
    m1_reason     TEXT,
    m2_reason     TEXT,
    m3_reason     TEXT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    m2_features   JSONB,
    UNIQUE (stock_id, vote_date)
);

CREATE TABLE IF NOT EXISTS user_news (
    id           SERIAL PRIMARY KEY,
    platform     VARCHAR(100),
    title        VARCHAR(500),
    content      TEXT,
    tickers      TEXT[],
    keywords     TEXT[] DEFAULT ARRAY[]::TEXT[],
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS news_features (
    id            SERIAL PRIMARY KEY,
    stock_id      VARCHAR(10)  NOT NULL,
    feature_date  DATE         NOT NULL,
    sentiment     FLOAT,
    keyword_hits  JSONB,
    article_count INT DEFAULT 0,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (stock_id, feature_date)
);
