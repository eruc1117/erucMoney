-- Iteration 58：程式交易引擎——規則、委託單生命週期、事件
--
-- 紙上交易（025）只有「成交紀錄」：清單出來、次日開盤照單全收。真正的程式交易在中間多一層「委託單」：
-- 引擎依規則產生委託（調倉、退出、停損）→ 送券商（紙上或凱基）→ 成交／未成交／取消，每一步都留痕，頁面才有東西可以觀察。
--   trading_engine_state  一列：開關、模式（paper／live）、券商（paper／kgi）、候選 run、規則 JSON、最後執行時間與錯誤
--   trading_orders        每張委託：哪天下、為什麼下（rebalance／exit／stop_loss）、限價、狀態、嘗試次數、成交價量、券商單號
--   trading_events        引擎做了什麼（signal、orders、fill、unfilled、stop_loss、guard、error），給觀察頁的時間軸
-- 紙上模式的成交仍寫進 portfolio_paper_trades（同一個模擬帳戶、同一條淨值曲線），委託單只是多記一層。

CREATE TABLE IF NOT EXISTS trading_engine_state (
    id              INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    enabled         BOOLEAN NOT NULL DEFAULT FALSE,
    mode            VARCHAR(8) NOT NULL DEFAULT 'paper',      -- paper / live
    broker          VARCHAR(16) NOT NULL DEFAULT 'paper',     -- paper / kgi
    run_id          INTEGER REFERENCES portfolio_runs(id) ON DELETE SET NULL,
    rules           JSONB NOT NULL DEFAULT '{}'::jsonb,       -- stop_loss_pct、rel_dd_guard、limit_slip、max_attempts（缺的用程式預設）
    last_run_at     TIMESTAMP,
    last_error      TEXT,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trading_orders (
    id              SERIAL PRIMARY KEY,
    mode            VARCHAR(8) NOT NULL,
    broker          VARCHAR(16) NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    order_date      DATE NOT NULL,                            -- 依哪一天收盤決定的（成交在下一個交易日）
    rebalance_date  DATE,                                     -- 調倉單：哪一份清單；停損單：NULL
    stock_id        VARCHAR(12) NOT NULL,
    side            VARCHAR(4) NOT NULL,                      -- buy / sell
    shares          INTEGER NOT NULL,
    limit_price     NUMERIC(12, 4),                           -- 零股限價：收盤 ±slip；NULL = 市價
    reason          VARCHAR(16) NOT NULL,                     -- rebalance / exit / stop_loss
    status          VARCHAR(12) NOT NULL DEFAULT 'pending',   -- pending / filled / unfilled / cancelled / rejected
    attempts        INTEGER NOT NULL DEFAULT 0,
    filled_shares   INTEGER NOT NULL DEFAULT 0,
    filled_price    NUMERIC(12, 4),
    filled_at       DATE,
    broker_ref      VARCHAR(64),
    note            TEXT,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_trading_orders_status ON trading_orders (status, order_date);
CREATE INDEX IF NOT EXISTS idx_trading_orders_rebalance ON trading_orders (rebalance_date);

CREATE TABLE IF NOT EXISTS trading_events (
    id              SERIAL PRIMARY KEY,
    ts              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    kind            VARCHAR(24) NOT NULL,
    stock_id        VARCHAR(12),
    detail          JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_trading_events_ts ON trading_events (ts DESC);
