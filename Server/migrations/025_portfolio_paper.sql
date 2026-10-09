-- Iteration 54：階段 4 紙上交易（模擬帳戶）
--
-- 為什麼不用 user_trades 加 account 欄位（計畫原本的寫法）：那張表綁使用者、用移動平均成本重放、給「我的持股」頁用；
-- 模擬帳戶要的是「照候選策略的清單機械式成交、每天結算對 0050」，混進去兩邊都難對帳。所以另開三張表：
--   portfolio_paper_state   一列：起始日、起始資金、現金、候選 run_id
--   portfolio_paper_trades  每筆模擬成交（次一交易日開盤、零股、同一套成本；一字鎖死不成交會記 filled=false）
--   portfolio_paper_nav     每個交易日的淨值與 0050（同起點），每月檢討從這裡算
-- portfolio_live_list 改成留歷史：同一個訊號日重算就覆蓋，不同月份各自保留。

CREATE TABLE IF NOT EXISTS portfolio_paper_state (
    id              INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    started_on      DATE NOT NULL,
    start_capital   NUMERIC(16, 2) NOT NULL,
    cash            NUMERIC(16, 2) NOT NULL,
    run_id          INTEGER REFERENCES portfolio_runs(id) ON DELETE SET NULL,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_paper_trades (
    id              SERIAL PRIMARY KEY,
    rebalance_date  DATE NOT NULL,                  -- 哪一個訊號日的清單
    trade_date      DATE NOT NULL,                  -- 成交日（訊號日的次一交易日）
    stock_id        VARCHAR(12) NOT NULL,
    side            VARCHAR(4) NOT NULL,            -- buy / sell
    shares          INTEGER NOT NULL,               -- 股（零股）
    price           NUMERIC(12, 4) NOT NULL,        -- 成交價（當日開盤）
    gross           NUMERIC(16, 2) NOT NULL,
    fee             NUMERIC(12, 2) NOT NULL DEFAULT 0,
    tax             NUMERIC(12, 2) NOT NULL DEFAULT 0,
    filled          BOOLEAN NOT NULL DEFAULT TRUE,  -- 一字鎖漲跌停 → false，shares 是原本要下的量
    note            TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_paper_trades_date ON portfolio_paper_trades (trade_date);

CREATE TABLE IF NOT EXISTS portfolio_paper_nav (
    trade_date      DATE PRIMARY KEY,
    nav             NUMERIC(16, 2) NOT NULL,        -- 現金 + 持股市值（收盤）
    cash            NUMERIC(16, 2) NOT NULL,
    bench_close     NUMERIC(12, 4),                 -- 0050 還原收盤
    n_holdings      INTEGER NOT NULL DEFAULT 0
);

-- 清單留歷史：同一訊號日同一檔只有一列
CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_live_list ON portfolio_live_list (rebalance_date, stock_id);
