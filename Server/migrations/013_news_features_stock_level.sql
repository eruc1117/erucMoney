-- Iteration 32：news_features 補上個股層級欄位
--
-- 症狀：同一天 26 檔的 `sentiment` 全是 0.541、`article_count` 全是 92。
--
-- 根因不是 MODEL-003 復發。Iteration 10 的個股過濾修正還在，
-- `_compute_features()` 確實算出 `stock_sentiment_72h` / `stock_articles`，
-- `_features_to_signal()` 也確實以它們為評分主體（所以投票訊號是分歧的）。
-- 問題只出在**落地**：`upsert_news_features()` 寫的是 `avg_sentiment_72h`
-- 與 `total_articles` —— 兩個全市場聚合值。
-- 個股特徵算了卻沒存，落地那一欄的橫斷面變異數恆為 0。
--
-- 後果是對下游沉默的：任何拿 `news_features` 當輸入的模型（XGBoost、
-- UnifiedModel/panel）看到的是一個常數欄，訓練不會報錯，只會學不到東西，
-- 而症狀看起來像「新聞沒有預測力」——把落地 bug 誤判成資料結論。
--
-- 為何新增欄位而不是改寫 `sentiment` 的意義：
-- 表內已有 253 列歷史，全是全市場口徑。就地改語義的話，同一欄在
-- 某個日期前後代表不同的東西，且沒有任何跡象可循（Iteration 18 的
-- close_price/adj_close 就是這種教訓）。新欄位對歷史列留 NULL——
-- NULL 誠實地表示「當時沒記錄」，填 0 則會謊稱「本股當天沒有新聞」。

ALTER TABLE news_features
    ADD COLUMN IF NOT EXISTS stock_sentiment     DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS stock_article_count INTEGER;

COMMENT ON COLUMN news_features.sentiment           IS '全市場：近 72h 時間衰減加權情緒均值';
COMMENT ON COLUMN news_features.article_count       IS '全市場：近 72h 文章總數';
COMMENT ON COLUMN news_features.stock_sentiment     IS '本股：僅「提及本股」的新聞之時間衰減加權情緒；本股無新聞時為 NULL（棄權），非 0';
COMMENT ON COLUMN news_features.stock_article_count IS '本股：近 72h 提及本股的文章數；Iteration 32 前的歷史列為 NULL';
