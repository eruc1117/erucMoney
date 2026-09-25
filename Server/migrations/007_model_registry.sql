-- Iteration 21：模型版本註冊 + 預測台帳
--
-- 解決的問題：在此之前所有模型都是「固定檔名、重訓直接覆寫」
-- （range_model.joblib / volatility.joblib / gap_model.joblib / m3_chip_rf.joblib
--   以及 LSTM 的 saved_models/<model_key>/<stock>.keras）。
-- 一旦重訓，上一版就永久消失，也無從得知線上那筆預測是哪一版算的。
--
-- 本表把「版本」變成一等公民：
--   candidate  正在迭代的版本，指向工作區路徑，會被下次重訓覆寫
--   frozen     已凍結的長期服役版本，指向不可變快照，永不被重訓覆寫
--   retired    曾經凍結、已被換下的版本（保留供回溯）
--
-- 每個 model_type 同時只允許一個 candidate（＝「原類型開一個新模型」的那一個），
-- 以及至多一個 is_serving（實際對外服務的版本）。

CREATE TABLE IF NOT EXISTS model_versions (
    id            SERIAL PRIMARY KEY,
    model_type    VARCHAR(60)  NOT NULL,   -- range / volatility / gap / m3_chip / lstm:m02_stacked
    version       INT          NOT NULL,
    status        VARCHAR(12)  NOT NULL DEFAULT 'candidate',   -- candidate / frozen / retired
    is_serving    BOOLEAN      NOT NULL DEFAULT FALSE,         -- 推論端實際載入的版本
    artifact_path TEXT         NOT NULL,   -- candidate：工作區；frozen：不可變快照
    target_kind   VARCHAR(24)  NOT NULL,   -- close / range / volatility / gap / signal
    horizon_days  INT,
    trained_at    TIMESTAMP,
    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    frozen_at     TIMESTAMP,
    retired_at    TIMESTAMP,
    freeze_reason VARCHAR(12),             -- auto（達門檻自動凍結）/ manual（使用者選取）
    freeze_note   TEXT,
    train_metrics JSONB,                   -- 訓練時的走查指標
    live_metrics  JSONB,                   -- 凍結當下的線上實測指標快照
    UNIQUE (model_type, version)
);

-- 一個類型只能有一個 candidate：凍結時自動開下一版，這條約束確保不會開出兩個
CREATE UNIQUE INDEX IF NOT EXISTS idx_model_versions_one_candidate
    ON model_versions (model_type) WHERE status = 'candidate';

-- 一個類型只能有一個服役版本
CREATE UNIQUE INDEX IF NOT EXISTS idx_model_versions_one_serving
    ON model_versions (model_type) WHERE is_serving;


-- 預測台帳
-- ─────────────────────────────────────────────────────────────────────────────
-- 每一次推論都留一筆，到期後回填實際值。這是自動凍結門檻的唯一資料來源，
-- 也讓「預測比對」頁面能涵蓋不產生逐日收盤價的模型（振幅／波動率／跳空／籌碼訊號）。
--
-- baseline_value 是關鍵欄位：本專案已反覆證明（Iteration 11、13、15）
-- 「模型準確率好看」在沒有天真基準對照時毫無意義。基準必須與預測**同時**寫下，
-- 事後才無法挑選對自己有利的基準。

CREATE TABLE IF NOT EXISTS model_predictions (
    id               BIGSERIAL PRIMARY KEY,
    model_version_id INT         NOT NULL REFERENCES model_versions(id) ON DELETE CASCADE,
    stock_id         VARCHAR(12) NOT NULL,
    target_kind      VARCHAR(24) NOT NULL,
    predicted_on     DATE        NOT NULL,   -- 作出預測時的資料截止日
    -- 預測所指的日期。寫入時只能以行事曆推估（未來交易日尚未進資料庫），
    -- 回填時會依真實交易日曆修正為第 horizon_days 個交易日。
    -- 因此**自然鍵是 horizon_days 而非 target_date**——否則修正日期會撞上唯一鍵。
    target_date      DATE        NOT NULL,
    horizon_days     INT         NOT NULL DEFAULT 1,
    ref_value        NUMERIC(16, 6),         -- 基準日參考值（方向判定的原點，如當日收盤）
    predicted_value  NUMERIC(16, 6) NOT NULL,
    baseline_value   NUMERIC(16, 6),         -- 天真基準的預測值（如「明日＝今日」）
    ci_low           NUMERIC(16, 6),
    ci_high          NUMERIC(16, 6),
    actual_value     NUMERIC(16, 6),         -- 到期後回填
    resolved_at      TIMESTAMP,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (model_version_id, stock_id, target_kind, predicted_on, horizon_days)
);

CREATE INDEX IF NOT EXISTS idx_model_pred_pending
    ON model_predictions (target_date) WHERE actual_value IS NULL;
CREATE INDEX IF NOT EXISTS idx_model_pred_version
    ON model_predictions (model_version_id, target_date);


-- 既有的使用者儲存預測：補記是哪一版模型算的
-- （既有資料無從追溯，維持 NULL；前端顯示為「未記錄版本」）
-- 注意：saved_predictions 是在 index.js 啟動流程建立的，而 migration 先於它執行，
-- 故此處需自帶 CREATE TABLE IF NOT EXISTS，否則全新資料庫會在這行失敗。
CREATE TABLE IF NOT EXISTS saved_predictions (
    id          SERIAL PRIMARY KEY,
    stock_id    VARCHAR(10)  NOT NULL,
    model_key   VARCHAR(50)  NOT NULL,
    model_label VARCHAR(100),
    saved_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    predictions JSONB NOT NULL
);

ALTER TABLE saved_predictions
    ADD COLUMN IF NOT EXISTS model_version_id INT REFERENCES model_versions(id) ON DELETE SET NULL;
