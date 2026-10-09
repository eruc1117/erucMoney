-- Iteration 53：訊號名加寬（組合訊號如 win3+mom+rev_streak 超過 16 字元寫不進日誌）
ALTER TABLE portfolio_runs ALTER COLUMN signal TYPE VARCHAR(40);
