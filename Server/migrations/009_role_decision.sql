-- Iteration 22：角色化決策欄位
--
-- 舊的 voting_results 只存三個方向訊號與一個加權分數。角色化之後多了三件事
-- 必須留下來，否則決策不可回溯：
--
--   roles          六個角色各自的訊號、理由與可信度標註
--   final_action   最終動作。比 final_signal 多了 Reduce／NoAdd——
--                  「減碼」和「不加碼」都不是買也不是賣，硬塞進三分類會失真
--   decision_path  每一步為什麼把訊號改成現在這樣
--
-- decision_path 是刻意加的。決策系統最糟的失敗模式不是判斷錯，
-- 而是「它說買，但沒人知道為什麼」——那種系統無法被檢討，也就無法被改進。

ALTER TABLE voting_results
    ADD COLUMN IF NOT EXISTS roles               JSONB,
    ADD COLUMN IF NOT EXISTS final_action        VARCHAR(10),
    ADD COLUMN IF NOT EXISTS target_position_pct NUMERIC(6, 2),
    ADD COLUMN IF NOT EXISTS decision_path       JSONB,
    ADD COLUMN IF NOT EXISTS holding_snapshot    JSONB;

-- 本週交易計畫（5 個交易日，每天一個動作）
--
-- 與 voting_results 分開存，因為它們回答的是不同層級的問題：
-- voting_results 回答「今天這檔怎麼看」，weekly_plans 回答
-- 「這一週要照什麼順序執行」。一週只產生一份，週中重跑會覆蓋。
CREATE TABLE IF NOT EXISTS weekly_plans (
    id            SERIAL PRIMARY KEY,
    stock_id      VARCHAR(12) NOT NULL,
    week_start    DATE        NOT NULL,   -- 該週週一
    generated_on  DATE        NOT NULL,   -- 產生計畫時的資料截止日
    policy_version VARCHAR(40),           -- 產生此計畫的策略參數版本
    days          JSONB       NOT NULL,   -- [{day, date, action, position_pct, reason}]
    expected      JSONB,                  -- 產生當下的預期值（振幅、停損、目標部位）
    realized      JSONB,                  -- 事後回填：實際報酬與各日實際動作是否合理
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (stock_id, week_start)
);

CREATE INDEX IF NOT EXISTS idx_weekly_plans_week ON weekly_plans (week_start);
