-- Migration 001: 為 stock_info.industry_type 新增索引，加速產業篩選查詢
-- Applied by Server/lib/migrate.js at startup

CREATE INDEX IF NOT EXISTS idx_stock_info_industry_type
  ON stock_info (industry_type);
