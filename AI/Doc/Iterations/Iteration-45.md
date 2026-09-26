# Iteration 45 — 固定自動測試腳本（非模型部分，第 1～4 期）

**日期：** 2026-09-26 ～ 27

## 起點

Iteration 44 之後整套平台只有行事曆後端有自動化測試（145 項、78%），股票 API 與爬蟲是 0，前端 3.5%。
使用者要求：整理「與預測資料模型無關」功能的固定自動測試腳本計畫並執行（第 5 期部署冒煙先不做）。
計畫本身在 Claude 的 artifact「自動測試腳本計畫」；本文件記錄實作結果。

## 結果總覽

| Repo | 之前 | 之後 | 覆蓋率 | CI |
|------|------|------|--------|----|
| meeting_API_Server | 145 項、5 失敗 | **229 項全過** | 91%（門檻 75%） | `.github/workflows/test.yml`（push／PR，postgres:16） |
| erucMoney `Server/` | 0 | **130 項全過** | 範圍內路由 85–100%（含模型路由 68%） | money `.github/workflows/test.yml` Node job |
| erucMoney `Crawler/` | 0 | **124 項全過**（17 項用測試庫） | — | 同上 crawler job |
| meeting_front_end 單元 | 27 項 | **72 項全過** | — | `pages.yml` 加 test job，過了才建置部署 |
| meeting_front_end E2E | 0 | **44 項全過**（10 支 spec） | — | `.github/workflows/e2e.yml` 每晚 03:00 UTC＋手動 |

## 各期做了什麼

### 第 1 期 行事曆後端
- 5 個舊失敗的真正原因：測試寫死 2025 年日期，`validateDateTime` 只接受一年前到兩年後，2026 起全部過期；改成相對日期。ipWhitelist 是模組載入時讀 `SOURCEIP`，測試先設好。
- 新增 http 層：`admin.test.js`（11）、`stock-proxy.test.js`（12，用真的假上游而非 nock——內建 fetch 攔不到）、`security.test.js`（5）、`db/migrations.test.js`（3）；auth／user 補 role 與停用案例。
- `.env.test` + `tests/setup-env.js`（DB_NAME 不是 `_test` 結尾直接 throw）、`tests/global-setup.js` 自動建 `Schedule_test` 並遷移。

### 第 2 期 股票 API
- `Server/app.js`（app + init）與 `index.js`（只 listen）拆開；`lib/proxy.js` 可用 `FASTAPI_HOST/PORT` 覆寫；`lib/migrate.js` 可帶連線。預設行為不變，正式 MoneyApi 重啟驗證過。
- `tests/unit`：tradeLedger（16）、auth 兩種 token（20）；`tests/http`：auth、holdings、news、stocks、admin-proxy、us、security；`tests/db/migrations`。helpers：seed 4 檔 × 30 交易日、假 FastAPI、假行事曆登入。
- 測試抓到的真 bug：`routes/news.js` PUT／DELETE 沒檢查作者（任何登入者能改刪別人的）→ 已修：只能動自己的，admin 可動任何一筆；`/auth/users` 沒回 `external_id`，管理頁的「行事曆 #id」一直顯示本地 → 已修。

### 第 3 期 爬蟲
- `Crawler/tests/` 9 檔、fixtures 全部手寫最小樣本，`responses` 攔截，不上網；`CRAWLER_TEST_DB=Stock_crawler_test` 由 `config.py` 讀（正式沒設此變數）。
- 照實作測、不硬湊計畫：排程時點是實際的 `config.SCHEDULE`（股價 18:00、投票 20:00、新聞每小時 :05、週預測週日 08:00）；Wayback 7 天上限在 Python 端不存在，未寫。
- 記錄未修的小瑕疵：`_month_in_title('十三月')` 回 13。

### 第 4 期 前端
- 單元 5 檔 45 項：AuthContext、股票 api／auth shim、StockApp 模式守門、router 守門。`tsconfig` exclude 加 `*.test.js(x)`（allowJs 會把測試拉進 build 型別檢查）。
- E2E：`e2e/stack.js` 一條指令起整個測試棧（Schedule_test 遷移、Stock_test bootstrap＋seed、假 FastAPI、股票測試後端 :3101、行事曆測試後端 :5100），Playwright globalSetup／Teardown 接上；10 支 spec 44 項。
- 為了 E2E：行事曆後端登入／註冊限流可用 `LOGIN_RATE_LIMIT`／`REGISTER_RATE_LIMIT` 覆寫（預設不變）。
- 記錄未修的行為：行程衝突偵測只抓「新區間包住既有活動」，新活動落在既有活動內部會被接受（spec 照現況斷言）。

## 怎麼跑

```
# 行事曆後端
cd meeting_API_Server && npm test
# 股票 API 與爬蟲
cd money/Server && npm test
cd money/Crawler && python -m pytest -q
# 前端
cd meeting_front_end && npm run test:unit && npm run test:e2e
```

測試庫：`Schedule_test`、`Stock_test`、`Stock_crawler_test`，都由測試自己建立與遷移；任何測試在 DB 名稱不是 `_test` 結尾時拒絕執行。

## 沒做的

- 第 5 期（部署冒煙 `Deploy/smoke.ps1`、分支保護）依指示先不做。
- `e2e.yml` 尚未在 GitHub 上跑過（要等本 commit 的 `external_id` 修正上去才會全綠）。
