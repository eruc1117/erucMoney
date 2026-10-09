---
paths:
  - "Server/migrations/**"
  - "Server/lib/migrate.js"
  - "Server/tests/db/migrations.test.js"
---

# Migration 規則

- 編號接著最大號碼（`NNN_snake_case.sql`），SQL 要冪等（`IF NOT EXISTS`、`ADD COLUMN IF NOT EXISTS`）。
- 檔頭註解寫：哪個 Iteration、為什麼要這張表／欄位、誰讀誰寫。
- 新增 migration 後更新 `Server/tests/db/migrations.test.js` 裡的數量，並跑 `npm test`（`tests/db/` 會建臨時庫 `Stock_migtest` 驗證）。
- **不要**直接對正式庫 `Stock` 下 `ALTER TABLE`／`DELETE`（auto mode 會擋，而且那是使用者該自己觸發的狀態變更）。
  Node 常駐工作 `MoneyApi` 重啟時 `lib/migrate.js` 會套用——完成報告要提醒使用者重啟。
- `portfolio_runs` 的列不能刪（DSR 的 N 就是列數，刪了 N 就是假的）。
