-- Iteration 28：期貨日／夜盤行情
--
-- 台指期夜盤（15:00~翌日 05:00）是市場在台股開盤前對次日的**直接定價**。
-- 探測結果（Crawler/probe_night_session.py，2024-01 起 14,880 筆）：
--
--   夜盤隱含隔夜變動 vs 個股開盤跳空   相關 +0.567
--   費半 SOXX 隔夜   vs 個股開盤跳空   相關 +0.483
--   R²：只用夜盤 0.3215、只用費半 0.2336、兩者一起 0.3319
--
-- 也就是說**夜盤幾乎吃掉了美股的全部資訊**（美股額外只貢獻 +0.0104），
-- 反過來卻不成立（夜盤額外貢獻 +0.0983）。這符合直覺：
-- 夜盤本來就是市場「看完美股之後」對台股開盤的定價。
--
-- 只存近月契約（當日該時段成交量最大者）。理由：
--   · 價差交易（contract_date 含 '/'）不是單一契約報價
--   · 「最小契約月」在結算日前後會挑到即將到期、流動性已移轉的那一口，
--     用成交量挑穩健得多
--
-- session 的語意（實測確認）：after_market 的收盤價幾乎等於**同一個 trade_date**
-- 的日盤開盤價（中位數差 0.185%），亦即該列夜盤領先同日開盤，不是落後。
-- 這點很重要——搞反就是未來資訊洩漏。

CREATE TABLE IF NOT EXISTS futures_daily (
    futures_id    VARCHAR(12) NOT NULL,     -- TX 台指期、MTX 小台、CDF 台積電期…
    trade_date    DATE        NOT NULL,
    session       VARCHAR(14) NOT NULL,     -- position（日盤）/ after_market（夜盤）
    contract_date VARCHAR(16),              -- 近月契約年月
    open_price    NUMERIC(14, 2),
    high_price    NUMERIC(14, 2),
    low_price     NUMERIC(14, 2),
    close_price   NUMERIC(14, 2),
    volume        BIGINT,
    open_interest BIGINT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (futures_id, trade_date, session)
);

CREATE INDEX IF NOT EXISTS idx_futures_daily_date
    ON futures_daily (trade_date, session);
