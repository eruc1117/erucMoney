# 把 Node.js API（Server/ :3001）註冊成 Windows 工作排程器的常駐工作（與 MoneyScheduler 同一種做法）
#
#   powershell -ExecutionPolicy Bypass -File Deploy\install_api_task.ps1
# 移除：Unregister-ScheduledTask MoneyApi -Confirm:$false
# 日誌：Server\logs\api.log
#
# 對外之前先把 Server\.env 填好（ALLOWED_ORIGINS、JWT_SECRET、ADMIN_PASSWORD、RATE_LIMIT_PER_MIN）。
# FastAPI :8000 與 LSTM :8001 仍由 start-dev.bat 或各自的方式啟動；沒開時相關頁面會回 503，登入與持股不受影響。

$ErrorActionPreference = 'Stop'
$TaskName = 'MoneyApi'
$Root     = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Server   = Join-Path $Root 'Server'
New-Item -ItemType Directory -Force (Join-Path $Server 'logs') | Out-Null

$node = (Get-Command node).Source
# 經 Deploy\run_logged.js 啟動：視窗標題 = MoneyApi，輸出同時印在視窗與寫進 log
$log = Join-Path $Server 'logs\api.log'
$runner = Join-Path $Root 'Deploy\run_logged.js'
$action = New-ScheduledTaskAction -Execute $node `
    -Argument "`"$runner`" $TaskName `"$log`" `"$node`" index.js" -WorkingDirectory $Server

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = 'PT1M'

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 2) `
    -MultipleInstances IgnoreNew -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Hidden

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
Get-NetTCPConnection -LocalPort 3001 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description '台股決策系統 Node.js API :3001（JWT、持股、代理 FastAPI／LSTM）' | Out-Null
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 4
Write-Host "已註冊 $TaskName：狀態 $((Get-ScheduledTask -TaskName $TaskName).State)"
Write-Host "日誌：$log"
try { Write-Host ("health: " + (Invoke-RestMethod http://localhost:3001/health).ok) } catch { Write-Host "health 尚未回應：$_" }
