@echo off
cd /d "%~dp0"
echo 安裝依賴套件...
npm install
echo.
echo 啟動 Node.js Server (port 3001)...
node index.js
pause
