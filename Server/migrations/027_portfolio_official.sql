-- Iteration 64：正式策略——候選 #44 升格；保留期開過一次；每日更新的「全期間至今」淨值
--
-- 一列：哪個候選、保留期那一次回測（凍結，不再動）、每日更新的 live 列（同參數、2018-01-01 到今天，每天收盤後重算一次，
-- 覆寫自己的 metrics／series／positions，不算新實驗）、升格日期與理由、最後更新時間。
-- 為什麼要分 holdout 與 live 兩列：保留期的數字是「只看一次」的證據，必須凍結；每日更新的曲線會一直變，兩者不能是同一列。

CREATE TABLE IF NOT EXISTS portfolio_official (
    id              INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    candidate_run_id INTEGER NOT NULL REFERENCES portfolio_runs(id),
    holdout_run_id  INTEGER REFERENCES portfolio_runs(id),
    live_run_id     INTEGER REFERENCES portfolio_runs(id),
    promoted_on     DATE NOT NULL,
    note            TEXT,
    last_update_at  TIMESTAMP,
    last_update_end DATE,                         -- live 列最後一次重算到哪一天的行情
    last_error      TEXT
);
