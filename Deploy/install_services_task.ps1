# 把 FastAPI（Crawler/ :8000）與 LSTM 推論（LSTM/ :8001）註冊成工作排程器常駐工作
# 做法同 MoneyScheduler／MoneyApi：登入即啟動、失敗自動重啟、日誌寫檔。
#
#   powershell -ExecutionPolicy Bypass -File Deploy\install_services_task.ps1
# 移除：Unregister-ScheduledTask MoneyCrawlerApi -Confirm:$false；Unregister-ScheduledTask MoneyLstm -Confirm:$false
# 日誌：Crawler\logs\api.log、LSTM\logs\serve.log
#
# 這兩個服務只聽本機（Node 代理過去），不進隧道。start-dev.bat 偵測到工作在跑就不會再開一份。

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Register-MoneyTask($Name, $WorkDir, $Exe, $Arguments, $Log, $Desc) {
    New-Item -ItemType Directory -Force (Split-Path -Parent $Log) | Out-Null
    $action = New-ScheduledTaskAction -Execute 'cmd.exe' `
        -Argument "/c `"`"$Exe`" $Arguments >> `"$Log`" 2>&1`"" -WorkingDirectory $WorkDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $trigger.Delay = 'PT1M'
    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 2) `
        -MultipleInstances IgnoreNew -StartWhenAvailable `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Hidden
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    if (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
    }
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Description $Desc | Out-Null
    Start-ScheduledTask -TaskName $Name
    Write-Host "已註冊 $Name → $Log"
}

$py = (Get-Command python).Source
Register-MoneyTask -Name 'MoneyCrawlerApi' -WorkDir (Join-Path $Root 'Crawler') -Exe $py -Arguments 'main.py --mode server' `
    -Log (Join-Path $Root 'Crawler\logs\api.log') -Desc '台股決策系統 FastAPI :8000（爬蟲、投票、模型目錄；只聽本機）'

$lstmPy = Join-Path $Root 'LSTM\venv\Scripts\python.exe'
if (-not (Test-Path $lstmPy)) { $lstmPy = $py }
Register-MoneyTask -Name 'MoneyLstm' -WorkDir (Join-Path $Root 'LSTM') -Exe $lstmPy -Arguments 'serve.py' `
    -Log (Join-Path $Root 'LSTM\logs\serve.log') -Desc '台股決策系統 LSTM 推論 :8001（只聽本機）'

Start-Sleep -Seconds 15
foreach ($t in 'MoneyCrawlerApi', 'MoneyLstm') { Write-Host "$t：$((Get-ScheduledTask -TaskName $t).State)" }
foreach ($u in 'http://localhost:8000/docs', 'http://localhost:8001/health') {
    try { Write-Host "$u → $((Invoke-WebRequest $u -UseBasicParsing -TimeoutSec 20).StatusCode)" }
    catch { Write-Host "$u 尚未回應：$($_.Exception.Message)（LSTM 載入模型可能要再等一下）" }
}
