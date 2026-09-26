-- Node API（Server/app.js）啟動時用 CREATE TABLE IF NOT EXISTS 建的四張表；
-- 測試庫沒有 Node 幫忙建，這裡照抄（migration 013、014 之後會再 ALTER）。
CREATE TABLE IF NOT EXISTS user_news (
  id           SERIAL PRIMARY KEY,
  platform     VARCHAR(100),
  title        VARCHAR(500),
  content      TEXT,
  tickers      TEXT[],
  keywords     TEXT[] DEFAULT ARRAY[]::TEXT[],
  submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS saved_predictions (
  id          SERIAL PRIMARY KEY,
  stock_id    VARCHAR(10)  NOT NULL,
  model_key   VARCHAR(50)  NOT NULL,
  model_label VARCHAR(100),
  saved_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  predictions JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS voting_results (
  id            SERIAL PRIMARY KEY,
  stock_id      VARCHAR(10)  NOT NULL,
  vote_date     DATE         NOT NULL,
  m1_signal     VARCHAR(4),
  m2_signal     VARCHAR(4),
  m3_signal     VARCHAR(4),
  final_signal  VARCHAR(4),
  score         FLOAT,
  weights       JSONB,
  m1_reason     TEXT,
  m2_reason     TEXT,
  m3_reason     TEXT,
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (stock_id, vote_date)
);
CREATE TABLE IF NOT EXISTS news_features (
  id            SERIAL PRIMARY KEY,
  stock_id      VARCHAR(10)  NOT NULL,
  feature_date  DATE         NOT NULL,
  sentiment     FLOAT,
  keyword_hits  JSONB,
  article_count INT DEFAULT 0,
  updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (stock_id, feature_date)
);
