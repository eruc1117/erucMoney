-- Iteration 17：除權息結果表
--
-- 用途：修正開盤跳空模型的系統性誤差。
-- 除權息日的價格缺口是配息／配股造成的**機械性**結果，不是市場對消息的反應。
-- 例如 2330 於 2026-06-11 除息 6 元：前日收盤 2255.0 → 參考價 2248.99，
-- 缺口 −0.27% 與美股隔夜走勢完全無關，模型若把它當成真實跳空學習即產生偏差。
--
-- reference_price（除權息參考價）是交易所計算的理論開盤基準，
-- 用它取代前一日收盤即可扣除機械性缺口。

CREATE TABLE IF NOT EXISTS stock_dividend_result (
    stock_id        VARCHAR(12)  NOT NULL,
    ex_date         DATE         NOT NULL,   -- 除權息交易日
    before_price    NUMERIC(14, 4),          -- 除權息前一日收盤
    reference_price NUMERIC(14, 4),          -- 除權息參考價（理論開盤基準）
    dividend        NUMERIC(14, 4),          -- 配息／配股金額
    dividend_type   VARCHAR(8),              -- 息 / 權 / 權息
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (stock_id, ex_date)
);

CREATE INDEX IF NOT EXISTS idx_dividend_result_date
    ON stock_dividend_result (ex_date);
