@echo off
set ROOT=%~dp0
set LSTM_PY=%ROOT%LSTM\venv\Scripts\python.exe

rem 三個後端若已由工作排程器常駐（MoneyCrawlerApi / MoneyLstm / MoneyApi，見 Deploy\install_*_task.ps1）就不再開
schtasks /query /tn MoneyCrawlerApi /fo list 2>nul | findstr /i "Running" >nul
if %errorlevel%==0 (echo [start-dev] FastAPI 已由 MoneyCrawlerApi 常駐) else (
    start "Crawler :8000"   cmd /k "cd /d %ROOT%Crawler & python main.py --mode server")
schtasks /query /tn MoneyLstm /fo list 2>nul | findstr /i "Running" >nul
if %errorlevel%==0 (echo [start-dev] LSTM 已由 MoneyLstm 常駐) else (
    start "Predict :8001"   cmd /k "cd /d %ROOT%LSTM & %LSTM_PY% serve.py")
schtasks /query /tn MoneyApi /fo list 2>nul | findstr /i "Running" >nul
if %errorlevel%==0 (echo [start-dev] Node API 已由 MoneyApi 常駐) else (
    start "Server :3001"    cmd /k "cd /d %ROOT%Server & npm run dev")
start "Screen Vite"     cmd /k "cd /d %ROOT%Screen & npm run dev"

rem 排程器：若已由工作排程器常駐（MoneyScheduler，見 Crawler\install_scheduler_task.ps1）
rem 就不要再開一份，否則同一個任務會跑兩次、FinMind 額度加倍消耗。
schtasks /query /tn MoneyScheduler /fo list 2>nul | findstr /i "Running" >nul
if %errorlevel%==0 (
    echo [start-dev] 排程器已由 MoneyScheduler 常駐，不另外啟動
) else (
    start "Scheduler"   cmd /k "cd /d %ROOT%Crawler & python main.py --mode schedule"
)
