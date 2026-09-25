# 移除 install_scheduler_task.ps1 註冊的常駐工作
$TaskName = 'MoneyScheduler'
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "已移除 $TaskName"
} else {
    Write-Host "$TaskName 不存在"
}
