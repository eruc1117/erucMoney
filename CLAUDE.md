# erucMoney — 專案指示（跨任務都成立的事實）

這個檔案只放**每一次任務都用得到**的事實。單次任務的進度、未解問題、下一步在 `progress.md`（交接筆記）；
偶爾才用的流程在 `.claude/skills/`；只碰某些路徑才適用的規則在 `.claude/rules/`。
本檔的內容如果和程式碼不符，以程式碼為準並回來改這裡。

## 專案是什麼

台股預測與「打敗大盤」月調倉研究平台。四個子系統：

| 目錄 | 內容 | 執行 |
|---|---|---|
| `Crawler/` | Python：爬蟲、FastAPI :8000（`api.py`）、排程器（`scheduler.py`）、月調倉回測（`portfolio_*.py`、`dsr.py`） | 常駐工作 `MoneyCrawlerApi`、`MoneyScheduler` |
| `Server/` | Node Express :3001：資料庫、認證、代理 FastAPI；migration 在 `Server/migrations/` | 常駐工作 `MoneyApi` |
| `Screen/` | Vite + React 儀表板（GitHub Pages → `stock.erucmoney.com`） | `npm run dev`（:5173） |
| `LSTM/`、`UnifiedModel/`、`NewsModels/` | 模型訓練與研究；結果寫在 `UnifiedModel/results/*.md` | 手動 |

文件索引：`AI/Doc/README.md`。需求：`AI/UserDoc/Spec.md`。部署：`Deploy/README.md`。測試：`Server/README.md`、`Crawler/tests/conftest.py`。

## 輸出放哪裡（每次任務結束都要能指出路徑）

- **迭代紀錄**：`AI/Doc/Iterations/Iteration-NN.md`（NN 接著最大號碼），並在 `AI/Doc/README.md` 的迭代表加一列。格式見 `.claude/rules/iterations.md`。
- **交接筆記**：`progress.md`（任務／產出／已完成／決策／未解／下一步／階段）。做完一個有意義的階段就更新；下一個 session 從它接手。
- **驗證結果**：`AI/progress/checks.json`——只能透過 `node AI/harness/record_check.js` 寫，不手改。儀表板「工作進度」頁讀它。
- **實驗結果**：`UnifiedModel/results/`（腳本產生，不手改）；回測一律寫進資料表 `portfolio_runs`（N 只增不減，失敗的也算）。
- **schema 變更**：`Server/migrations/NNN_*.sql`（冪等）；不直接對正式庫 `Stock` 下 ALTER／DELETE。見 `.claude/rules/migrations.md`。

## 慣例

- 文件、註解、commit 訊息用繁體中文（台灣用語）；註解寫「為什麼」，不重述程式碼。
- 日期一律寫絕對日期（2026-10-09），不寫「昨天」「上週」。
- 技術主張要有來源：Anthropic／Claude Code 的事用官方文件，資料來源的事用 `AI/Doc/DataSources.md`，數字要能在結果檔或資料表裡找到。
- 不要 commit、不要 push，除非使用者明說。
- 保留期（2024-10 起）只能開一次（`--holdout-once`）；沒有使用者明確要求絕不開。
- 不在驗證期上挑參數；候選維持 `portfolio_runs` 標記 `candidate` 的那組，換候選是使用者的決定。

## 執行環境

- Windows 11；主控台 cp950 → 跑 Python 報表時設 `PYTHONUTF8=1`（settings.json 的 env 已設）。
- 測試：`Server/`：`npm test`（對 `Stock_test`，不能平行）；`Crawler/`：`python -m pytest -q`（DB 測試自動 skip 若測試庫不在）。
  跑測試請透過 `node AI/harness/record_check.js --name <名稱> --cwd <目錄> -- <指令>`，結果才會進 `checks.json`。
- 改了 `Crawler/api.py`、`Crawler/scheduler.py`、`Server/routes/*`、`Server/app.js` 後要重啟常駐工作（`Stop-ScheduledTask`／`Start-ScheduledTask MoneyCrawlerApi|MoneyScheduler|MoneyApi`）——這一步由使用者做，完成報告裡要提醒。
- 前端改完要 `cd Screen && npm run build` 確認編得過；push 後 GitHub Pages 約 3 分鐘自動部署。

## 完成的定義

一個任務「做完」的意思是：產出檔案存在、驗證結果記在 `checks.json`、`progress.md` 已更新、
完成報告列出**輸出路徑與驗證結果**（通過／失敗／略過各幾項、失敗的是哪些）。沒跑的測試要寫「沒跑」。

## Effort 與角色

主 session 用預設 effort；`evidence-reviewer`、`strategy-critic` 用 high（在 agent frontmatter 設定），`test-runner` 用 low。
審查者只能讀不能改；修正留給主 session。審查最多三輪，第三輪仍 FAIL 就把未解的反對意見附在報告裡交回使用者。

## 無人看管時

一則沒有工具呼叫的訊息會結束回合、工作就停了。不要用「接下來我會…」的摘要、「要不要我繼續」的詢問、
或「到了一個段落先報告」來結束回合；狀態說明放在下一個工具呼叫的同一則訊息裡，做到完成或真的被擋住為止。
