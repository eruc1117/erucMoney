-- Iteration 51：月調倉實驗日誌的標記與淨值曲線（前端「月調倉」頁要畫圖）
--
-- portfolio_runs.tag：'candidate' = 目前候選（開發期、驗證期、全期間各一列），前端頁首顯示；其他列是搜尋過程。
-- portfolio_run_series：每個 run 的日淨值（組合、0050 同一起點 = 1）。Iteration 49/50 的 44 次只存了指標，
-- 由 portfolio_backtest.py --attach-series 用當時的參數重算補上（不算新的實驗，N 不動）。

ALTER TABLE portfolio_runs ADD COLUMN IF NOT EXISTS tag VARCHAR(16);

CREATE TABLE IF NOT EXISTS portfolio_run_series (
    run_id      INTEGER NOT NULL REFERENCES portfolio_runs(id) ON DELETE CASCADE,
    trade_date  DATE    NOT NULL,
    nav         NUMERIC(14, 6) NOT NULL,     -- 組合淨值（起點 1）
    bench       NUMERIC(14, 6) NOT NULL,     -- 0050 含息淨值（起點 1）
    PRIMARY KEY (run_id, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_runs_tag ON portfolio_runs (tag);
