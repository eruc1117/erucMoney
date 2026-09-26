# 把行事曆平台的 Node.js API（meeting_API_Server :5000）註冊成工作排程器常駐工作 MoneyCalendarApi
# 前提：E:\Desktop\coding\meeting_API_Server 已 clone、npm install 過、.env 填好（DB、SECRET、ALLOWED_ORIGINS、STOCK_API_URL）。
# 對外：Cloudflare Tunnel 的 calendar-api.erucmoney.com → localhost:5000（Deploy/cloudflared-config.yml）。
#
#   powershell -ExecutionPolicy Bypass -File Deploy\install_calendar_api_task.ps1
# 移除：Unregister-ScheduledTask MoneyCalendarApi -Confirm:$false
# 日誌：meeting_API_Server\logs\api.log（pino）、logs\task.out（stdout/stderr）

$ErrorActionPreference = 'Stop'
$TaskName = 'MoneyCalendarApi'
$Repo = 'E:\Desktop\coding\meeting_API_Server'
if (-not (Test-Path (Join-Path $Repo 'server.js'))) { throw "找不到 $Repo\server.js" }
if (-not (Test-Path (Join-Path $Repo '.env'))) { throw "$Repo\.env 不存在，先照 README 建好" }
New-Item -ItemType Directory -Force (Join-Path $Repo 'logs') | Out-Null

$node = (Get-Command node).Source
$log = Join-Path $Repo 'logs\task.out'   # 應用程式本身的 pino 寫 logs\api.log，stdout 另外導到 task.out 以免 EBUSY
# 經 Deploy\run_logged.js 啟動：視窗標題 = MoneyCalendarApi，輸出同時印在視窗與寫進 log
$runner = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'run_logged.js'
$action = New-ScheduledTaskAction -Execute $node `
    -Argument "`"$runner`" $TaskName `"$log`" `"$node`" server.js" -WorkingDirectory $Repo
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
Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description '行事曆平台 Node.js API :5000（統一登入來源；經 calendar-api.erucmoney.com 對外）' | Out-Null
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 6
Write-Host "已註冊 $TaskName：狀態 $((Get-ScheduledTask -TaskName $TaskName).State)"
Write-Host "日誌：$log"
try { $r = Invoke-WebRequest http://localhost:5000/api/user/info -UseBasicParsing -TimeoutSec 10 } catch { $r = $_.Exception.Response }
Write-Host ("health（預期 401 未登入）：" + $(if ($r) { [int]$r.StatusCode } else { '無回應' }))
