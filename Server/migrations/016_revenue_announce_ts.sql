-- Iteration 39：月營收公布「時間」與來源
--
-- 006 建表時假設 FinMind create_time 就是公布日，實際上 2026-03 之前的資料 create_time 為空，
-- 表裡只有 151 筆、全在 2026-04 之後，做不了事件研究。
-- 現在公布時點改成多來源合成（Crawler/backfill_revenue_dates.py）：
--   mops_item   MOPS 重大訊息「公告本公司 X 月營收」（精確到秒）
--   cnyes_item  鉅亨網「營收速報 - 公司(代號)X月營收…」個股快訊（精確到秒；大型股才有）
--   news_item   其他媒體標題含「X月營收」的最早一則（精確到秒）
--   finmind     FinMind create_time（只有日期，2026-03 起）
--   cnyes_list  鉅亨網每日「台股大型／中小型公司 X 月營收一覽」清單（前一日公布 → 日期；2024-04 起全市場）
-- announce_date 改成可為 NULL：沒有公布時點的月份也要留營收數字，算意外程度要用前 15 個月。

ALTER TABLE stock_revenue_announce ALTER COLUMN announce_date DROP NOT NULL;
ALTER TABLE stock_revenue_announce ADD COLUMN IF NOT EXISTS announce_ts     TIMESTAMP;
ALTER TABLE stock_revenue_announce ADD COLUMN IF NOT EXISTS announce_source VARCHAR(16);
ALTER TABLE stock_revenue_announce ADD COLUMN IF NOT EXISTS updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

UPDATE stock_revenue_announce SET announce_source = 'finmind'
 WHERE announce_date IS NOT NULL AND announce_source IS NULL;
