-- Iteration 22：使用者持股
--
-- 在此之前，投票引擎對「使用者手上有什麼」一無所知，於是產生兩個實質問題：
--
--   1. 對沒持有的股票發 Sell 訊號毫無意義——本系統不做放空，
--      那個訊號使用者根本無法執行。
--   2. 部位建議（`position_pct`）算的是「該押多少」，卻不知道「已經押了多少」，
--      無法回答真正該回答的問題：加碼、減碼、還是不動。
--
-- 成本一併記錄，才能算出浮動損益，讓停損／停利成為可執行的決策而不是紙上談兵。
--
-- shares 用 NUMERIC 而非 INTEGER：零股交易存在，1.5 張是合法持有量。

CREATE TABLE IF NOT EXISTS user_holdings (
    id         SERIAL PRIMARY KEY,
    stock_id   VARCHAR(12)    NOT NULL,
    shares     NUMERIC(16, 3) NOT NULL CHECK (shares > 0),   -- 股數（非張數）
    avg_cost   NUMERIC(16, 4) NOT NULL CHECK (avg_cost > 0), -- 每股平均成本
    note       TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (stock_id)
);

CREATE INDEX IF NOT EXISTS idx_user_holdings_stock ON user_holdings (stock_id);
