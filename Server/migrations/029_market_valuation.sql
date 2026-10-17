-- Iteration 78：全市場個股估值（本益比、殖利率、股價淨值比）——Papers.md P51／P52 的資料前提（價值訊號 H18；資料工作，不算 N）
--
-- 為什麼要新表：庫裡沒有財報，也沒有全市場的股利；交易所每天公布「個股日本益比、殖利率及股價淨值比」
-- （證交所 BWIBBU_d、櫃買 peQryDate）。Iteration 80 查過（val-pit-check-80）：證交所檔的殖利率逐股在董事會後切換、兩市本益比在季報日更新——點時；
-- 但櫃買檔的殖利率整年固定、1 月 2 日就印當年春天才決議的股利（公告前含未來資訊），用它做訊號在年初有前視，要另補股利公告日。
-- 一天兩次呼叫拿全市場，不吃 FinMind 額度——和 market_daily_prices、market_institutional_daily 同一條路線。
-- 欄位：證交所有收盤價與財報年/季、沒有每股股利；櫃買有每股股利、沒有收盤價——各自留空。
-- 本益比虧損時交易所印「-」（櫃買印 N/A）→ NULL；殖利率(%) 與股價淨值比照原值存。
-- 誰寫：Crawler/valuation_data.py（回補與每日 18:37 排程 job_valuation_daily）。誰讀：之後的 portfolio_signal 價值訊號（dy、ep）。

CREATE TABLE IF NOT EXISTS market_valuation_daily (
    stock_id            VARCHAR(10)   NOT NULL,
    trade_date          DATE          NOT NULL,
    close_price         NUMERIC(12,2),
    pe                  NUMERIC(10,2),
    dividend_yield      NUMERIC(8,2),                 -- 交易所給的百分比值（4.12 ＝ 4.12%）
    pb                  NUMERIC(10,2),
    dividend_per_share  NUMERIC(12,4),                -- 櫃買才有
    dividend_year       SMALLINT,                     -- 民國年（交易所原值）
    fin_period          VARCHAR(10),                  -- 證交所才有：財報年/季，例 112/3
    source              VARCHAR(10)   NOT NULL,       -- twse / tpex
    fetched_at          TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (stock_id, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_market_valuation_date ON market_valuation_daily (trade_date);
