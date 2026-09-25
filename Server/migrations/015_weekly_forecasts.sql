-- 每週自動預測（Iteration 37）
--
-- 每星期日由排程器跑一次：用所有可用模型，對所有已有股票（台股追蹤清單 + 美股標的）
-- 產出「下一週」與「下下週」的預測，存下來直接顯示，不需要人工觸發。
--
-- 兩張表：runs 記一次執行的中繼資料（基準日、涵蓋週、哪些模型失敗），
-- forecasts 每列一個 (執行, 市場, 股票, 模型) 的結果，payload 依模型而異。
-- 不塞進 model_predictions：那張表是「一筆預測一個目標值」的台帳，
-- 這裡存的是整段路徑與多個欄位，語意不同。
CREATE TABLE IF NOT EXISTS weekly_forecast_runs (
    id            SERIAL PRIMARY KEY,
    run_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    trigger       VARCHAR(16) NOT NULL DEFAULT 'schedule',   -- schedule / catch_up / manual
    base_date     DATE,                                       -- 行情最後一日
    week1_start   DATE NOT NULL,
    week1_end     DATE NOT NULL,
    week2_start   DATE NOT NULL,
    week2_end     DATE NOT NULL,
    n_stocks      INTEGER NOT NULL DEFAULT 0,
    n_models      INTEGER NOT NULL DEFAULT 0,
    n_rows        INTEGER NOT NULL DEFAULT 0,
    errors        JSONB NOT NULL DEFAULT '[]'::jsonb,
    finished_at   TIMESTAMP
);

CREATE TABLE IF NOT EXISTS weekly_forecasts (
    id          SERIAL PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES weekly_forecast_runs(id) ON DELETE CASCADE,
    market      VARCHAR(4) NOT NULL,                 -- tw / us
    stock_id    VARCHAR(10) NOT NULL,
    model_key   VARCHAR(40) NOT NULL,                -- 與 model_catalog 的 key 一致
    payload     JSONB NOT NULL,
    UNIQUE (run_id, market, stock_id, model_key)
);

CREATE INDEX IF NOT EXISTS idx_weekly_forecasts_run ON weekly_forecasts (run_id, market);
