-- Iteration 18：還原權值收盤價 + 減資資料表
--
-- 背景：Iteration 17 以「讀取端替換前一日收盤」的方式修正除權息，
-- 但那只解決了兩個模型的路徑。任何直接查 stock_daily_prices 計算報酬率的
-- 程式碼仍會踩到同樣的坑（除權息日出現數 %~20% 的假跌幅）。
--
-- 根本解法是新增 adj_close 欄位，與 us_daily_prices.adj_close 一致：
--   adj_close[t] = close[t] × ∏(factor for every corporate action after t)
--   factor = 參考價 ÷ 事件前收盤
-- 如此「用 adj_close 算報酬」在任何地方都自動正確，不需要各處記得做調整。
--
-- 減資與除權息方向相反：除權息參考價低於前收（配息發出去），
-- 減資參考價高於前收（股份被註銷）。兩者都用同一套 factor 公式處理。

ALTER TABLE stock_daily_prices
    ADD COLUMN IF NOT EXISTS adj_close NUMERIC(14, 4);

COMMENT ON COLUMN stock_daily_prices.adj_close IS
    '還原除權息與減資後的收盤價；計算報酬率請一律使用本欄，close 僅供顯示';

CREATE TABLE IF NOT EXISTS stock_capital_reduction (
    stock_id        VARCHAR(12) NOT NULL,
    ex_date         DATE        NOT NULL,   -- 減資後首個交易日
    before_price    NUMERIC(14, 4),         -- 最後交易日收盤
    reference_price NUMERIC(14, 4),         -- 減資後參考價
    reason          VARCHAR(80),            -- 減資原因（Cash refund / Loss offset 等）
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (stock_id, ex_date)
);

CREATE INDEX IF NOT EXISTS idx_capital_reduction_date
    ON stock_capital_reduction (ex_date);
