-- Iteration 23：交易紀錄（分批進出與已實現損益）
--
-- Iteration 22 的持股只存一張「目前快照」：同一檔再次輸入就覆蓋，
-- 於是三件事算不出來——
--
--   1. 已實現損益。賣掉的部分賺賠多少，完全沒有留下
--   2. 分批進出後的成本變化。加碼會拉高平均成本，快照模式只能手算再手填
--   3. 決策的事後檢討。系統建議買進、使用者到底有沒有買、買在哪裡，無從對照
--
-- 本表是交易台帳，`user_holdings` 改為由它**回放推導**：
-- 每次新增或刪除交易，就把該股票的所有交易依日期重放一次，
-- 重算股數與平均成本。台帳是事實，持倉是結論——結論永遠可以從事實重建。
--
-- ## 成本基礎採移動平均法
--
-- 台股個人投資人不需要逐筆指定成本，移動平均法也是券商對帳單的慣例：
--
--     買進：新平均成本 = (原股數×原成本 + 本次價金 + 手續費) ÷ 新股數
--     賣出：已實現損益 = 本次價金 − 賣出股數×平均成本 − 手續費 − 證交稅
--           平均成本不變（賣出不改變剩餘部位的成本基礎）
--
-- 手續費計入成本、賣出的費稅直接扣在已實現損益上——這是實際入袋的算法。
-- 不計費用的損益數字看起來永遠比真實情況好，那正是最該避免的自我欺騙。

CREATE TABLE IF NOT EXISTS user_trades (
    id            SERIAL PRIMARY KEY,
    stock_id      VARCHAR(12)    NOT NULL,
    trade_date    DATE           NOT NULL,
    side          VARCHAR(4)     NOT NULL CHECK (side IN ('Buy', 'Sell')),
    shares        NUMERIC(16, 3) NOT NULL CHECK (shares > 0),
    price         NUMERIC(16, 4) NOT NULL CHECK (price > 0),
    fee           NUMERIC(16, 2) NOT NULL DEFAULT 0,   -- 手續費
    tax           NUMERIC(16, 2) NOT NULL DEFAULT 0,   -- 證交稅（僅賣出）
    note          TEXT,
    -- 以下由回放計算後回填，不由使用者輸入
    avg_cost_after NUMERIC(16, 4),   -- 這筆交易後的平均成本
    shares_after   NUMERIC(16, 3),   -- 這筆交易後的持股數
    realized_pnl   NUMERIC(16, 2),   -- 本筆已實現損益（僅賣出）
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_trades_stock
    ON user_trades (stock_id, trade_date, id);

-- 持倉來源：manual = 使用者直接輸入的快照；trades = 由交易台帳回放推導。
-- 有交易紀錄的股票不允許手動改持倉——否則台帳與結論會各說各話。
ALTER TABLE user_holdings
    ADD COLUMN IF NOT EXISTS source VARCHAR(8) NOT NULL DEFAULT 'manual',
    ADD COLUMN IF NOT EXISTS realized_pnl NUMERIC(16, 2) NOT NULL DEFAULT 0;
