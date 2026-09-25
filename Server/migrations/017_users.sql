-- 階段 1（多使用者）：users 表；持股、交易、手動新聞加 user_id
--
-- 既有資料全部歸 id = 1 的 admin（由 index.js 啟動時用環境變數 ADMIN_USER / ADMIN_PASSWORD 建立，
-- 密碼雜湊在 Node 端算，SQL 這裡只先插一列占位、密碼為空字串＝不能登入，等 index.js 補上雜湊）。
-- user_holdings 的唯一鍵從 (stock_id) 改成 (user_id, stock_id)：同一檔股票每個人各有一列。

CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(50)  NOT NULL UNIQUE,
    password_hash VARCHAR(100) NOT NULL DEFAULT '',
    role          VARCHAR(10)  NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    display_name  VARCHAR(100),
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP
);

INSERT INTO users (id, username, role, display_name)
VALUES (1, 'admin', 'admin', '管理者')
ON CONFLICT (id) DO NOTHING;
SELECT setval('users_id_seq', GREATEST((SELECT MAX(id) FROM users), 1));

ALTER TABLE user_holdings ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE user_trades   ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE user_news     ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE user_holdings DROP CONSTRAINT IF EXISTS user_holdings_stock_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_holdings_user_stock ON user_holdings (user_id, stock_id);
CREATE INDEX IF NOT EXISTS idx_user_trades_user ON user_trades (user_id, stock_id, trade_date, id);
