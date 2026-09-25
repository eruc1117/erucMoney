-- Iteration 20：月營收公布日
--
-- 用途：事件特徵。台股個股在營收公布、除權息等事件前後振幅明顯偏大，
-- 而這些日期**事先可知**，是少數能確定提升振幅預測的資訊。
--
-- 只存「公布日」而非營收數字——本表的用途是事件時間點，不是基本面分析。
-- FinMind TaiwanStockMonthRevenue 的 create_time 即為實際公布日
-- （date 欄位是營收所屬月份，不是公布日，兩者不可混用）。

CREATE TABLE IF NOT EXISTS stock_revenue_announce (
    stock_id      VARCHAR(12) NOT NULL,
    revenue_month DATE        NOT NULL,   -- 營收所屬月份（月初）
    announce_date DATE        NOT NULL,   -- 實際公布日（create_time）
    revenue       NUMERIC(20, 0),
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (stock_id, revenue_month)
);

CREATE INDEX IF NOT EXISTS idx_revenue_announce_date
    ON stock_revenue_announce (announce_date);
