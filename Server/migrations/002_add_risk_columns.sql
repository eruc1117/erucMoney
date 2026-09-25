-- Iteration 13：投票結果加入風險欄位（波動率預測 → 部位大小與停損距離）
--
-- 這些欄位不參與投票計分。M1/M2/M3 回答「買還是賣」，風險模組回答「押多少、
-- 停損放哪」，兩者正交。實測方向預測超越基準 -0.09%（無預測力），
-- 波動率預測相關係數 0.606、R²(log) 0.483，故只用後者做風險控管。

ALTER TABLE voting_results
    ADD COLUMN IF NOT EXISTS predicted_vol NUMERIC(8, 5),   -- 預測日波動率（小數）
    ADD COLUMN IF NOT EXISTS vol_regime    VARCHAR(4),      -- 低 / 中 / 高
    ADD COLUMN IF NOT EXISTS stop_pct      NUMERIC(6, 2),   -- 建議停損距離（%）
    ADD COLUMN IF NOT EXISTS position_pct  NUMERIC(6, 2),   -- 建議部位比例（%）
    ADD COLUMN IF NOT EXISTS risk_reason   TEXT;

CREATE INDEX IF NOT EXISTS idx_voting_results_vol_regime
    ON voting_results (vote_date, vol_regime);
