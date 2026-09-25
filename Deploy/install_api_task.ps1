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
# cmd /c 包一層才能把 stdout/stderr 導到檔案；視窗用 -WindowStyle Hidden 隱藏
$log = Join-Path $Server 'logs\api.log'
$action = New-ScheduledTaskAction -Execute 'cmd.exe' `
    -Argument "/c `"`"$node`" index.js >> `"$log`" 2>&1`"" -WorkingDirectory $Server

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = 'PT1M'

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 2) `
    -MultipleInstances IgnoreNew -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Hidden

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description '台股決策系統 Node.js API :3001（JWT、持股、代理 FastAPI／LSTM）' | Out-Null
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 4
Write-Host "已註冊 $TaskName：狀態 $((Get-ScheduledTask -TaskName $TaskName).State)"
Write-Host "日誌：$log"
try { Write-Host ("health: " + (Invoke-RestMethod http://localhost:3001/health).ok) } catch { Write-Host "health 尚未回應：$_" }
