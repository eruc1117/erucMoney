-- 美股趨勢預測與預測比對
--
-- `saved_predictions` 原本只服務台股：實際值一律去 `stock_daily_prices` 查。
-- 現在同一張表也要收美股的 LSTM 預測，比對時得去 `us_daily_prices` 取價。
-- 用一個 `market` 欄位分流，不用 stock_id 的長相猜——'TSM' 與 '2330'
-- 剛好長得不一樣，但那是巧合不是規則（與 resolve_predictions 的 US_KINDS 同一個理由）。
ALTER TABLE saved_predictions
    ADD COLUMN IF NOT EXISTS market VARCHAR(4) NOT NULL DEFAULT 'tw';

CREATE INDEX IF NOT EXISTS idx_saved_predictions_market
    ON saved_predictions (market, saved_at DESC);
