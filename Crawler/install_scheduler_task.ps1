# 把排程器註冊成 Windows 工作排程器的常駐工作（Iteration 36）
#
# 為什麼不用 NSSM／Windows Service：需要額外下載，而且服務帳號沒有使用者的
# 環境（Python 路徑、DB 設定都在使用者層）。工作排程器內建、登入即啟動、
# 失敗自動重啟，對單機自用足夠。
#
# 用法（一般權限即可，不必系統管理員；請自己執行，這一步不由程式代勞）：
#   powershell -ExecutionPolicy Bypass -File Crawler\install_scheduler_task.ps1
# 移除：uninstall_scheduler_task.ps1
# 查看：Get-ScheduledTask MoneyScheduler | Get-ScheduledTaskInfo
# 日誌：Crawler\logs\scheduler.log

$ErrorActionPreference = 'Stop'
$TaskName = 'MoneyScheduler'
$Crawler  = Split-Path -Parent $MyInvocation.MyCommand.Path

# pythonw：沒有主控台視窗，日誌全部走 logs/scheduler.log
$py = (Get-Command python).Source
$pyw = Join-Path (Split-Path -Parent $py) 'pythonw.exe'
if (-not (Test-Path $pyw)) { $pyw = $py }

$action = New-ScheduledTaskAction -Execute $pyw `
    -Argument 'main.py --mode schedule' -WorkingDirectory $Crawler

# 登入即啟動（Interactive：不必存密碼，登出就停，符合單機自用）
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = 'PT1M'    # 等 PostgreSQL 起來

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 2) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description '台股決策系統排程器：每日行情／籌碼／持股、每小時新聞、每日投票與模型評估' | Out-Null

Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 3
$info = Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo
Write-Host "已註冊 $TaskName：狀態 $((Get-ScheduledTask -TaskName $TaskName).State)，上次啟動 $($info.LastRunTime)"
Write-Host "日誌：$Crawler\logs\scheduler.log"
