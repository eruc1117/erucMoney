-- Iteration 52：候選策略「現在該買哪些」的清單（前端月調倉頁頁首）
--
-- 用候選的參數從 2018 一路算到最近一個訊號日，只留下最後一次調倉的目標持股；
-- 保留期的績效不算、不存、不印（分批輪動有路徑依賴，所以要從頭算，但只取名單）。
-- 每次重算整批替換；之後階段 4 的每月排程也寫這張表。

CREATE TABLE IF NOT EXISTS portfolio_live_list (
    id              SERIAL PRIMARY KEY,
    computed_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    run_id          INTEGER REFERENCES portfolio_runs(id) ON DELETE SET NULL,   -- 參數來自哪一列候選
    rebalance_date  DATE NOT NULL,                 -- 訊號日
    exec_date       DATE,                          -- 成交日（次一交易日開盤）
    stock_id        VARCHAR(12) NOT NULL,
    stock_name      VARCHAR(50),
    rank            INTEGER,
    signal_value    NUMERIC(14, 6),
    target_weight   NUMERIC(8, 6) NOT NULL,
    is_new          BOOLEAN NOT NULL DEFAULT FALSE  -- 這個月新進場的那一批
);

CREATE INDEX IF NOT EXISTS idx_portfolio_live_list_date ON portfolio_live_list (rebalance_date);
