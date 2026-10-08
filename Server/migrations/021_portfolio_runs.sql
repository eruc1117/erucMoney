-- Iteration 49：打敗大盤計畫階段 2——月調倉回測的實驗日誌
--
-- 多重測試懲罰（Deflated Sharpe Ratio）要知道「到底試過幾個版本」，所以每一次回測都寫一列，
-- experiment_n 只增不減、不能刪（刪了 N 就是假的）。metrics 放對 0050 的比較指標（JSONB，欄位見
-- Crawler/portfolio_backtest.py），positions 放每次調倉的持股，之後紙上交易與實單要對帳用。

CREATE TABLE IF NOT EXISTS portfolio_runs (
    id              SERIAL PRIMARY KEY,
    run_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    experiment_n    INTEGER NOT NULL,                 -- 第幾次嘗試（全域遞增，DSR 的 N）
    name            VARCHAR(80) NOT NULL,
    signal          VARCHAR(16) NOT NULL,             -- sue / ar0 / win …
    segment         VARCHAR(16) NOT NULL,             -- dev / valid / holdout / paper / live
    period_start    DATE NOT NULL,
    period_end      DATE NOT NULL,
    params          JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics         JSONB NOT NULL DEFAULT '{}'::jsonb,
    n_rebalances    INTEGER NOT NULL DEFAULT 0,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS portfolio_positions (
    run_id          INTEGER NOT NULL REFERENCES portfolio_runs(id) ON DELETE CASCADE,
    rebalance_date  DATE NOT NULL,                    -- 訊號日（收盤後算）
    exec_date       DATE,                             -- 實際成交日（次一交易日開盤）
    stock_id        VARCHAR(12) NOT NULL,
    rank            INTEGER,
    signal_value    NUMERIC(14, 6),
    target_weight   NUMERIC(8, 6) NOT NULL,
    filled          BOOLEAN NOT NULL DEFAULT TRUE,    -- 開盤鎖漲跌停視為未成交
    PRIMARY KEY (run_id, rebalance_date, stock_id)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_runs_signal ON portfolio_runs (signal, segment);
