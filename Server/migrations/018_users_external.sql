-- 單一登入（SSO）：股票系統接受行事曆平台（meeting_API_Server）簽的 JWT。
-- 行事曆的使用者 id 記在 external_id；第一次拿行事曆 token 打進來時，lib/auth.js 自動建立這一列
-- （password_hash 留空＝不能用本地密碼登入，只能經行事曆登入）。
ALTER TABLE users ADD COLUMN IF NOT EXISTS external_id INTEGER;
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_external_id ON users (external_id) WHERE external_id IS NOT NULL;
