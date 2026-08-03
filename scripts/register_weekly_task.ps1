#Requires -Version 5.1
<#
  註冊 / 更新 Windows 排程工作 "QuantCore-WeeklyTrack"。
  觸發：每週六 09:00；錯過起始時間（電腦關機/睡眠）→ 開機後儘快補跑。
  重跑本腳本會覆蓋既有同名工作（-Force）。
  移除：Unregister-ScheduledTask -TaskName 'QuantCore-WeeklyTrack' -Confirm:$false
#>

$TaskName = 'QuantCore-WeeklyTrack'
$Script   = 'C:\Users\user\QuantSystem\scripts\weekly_track.ps1'

$Action = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Script`""

$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At 9:00AM

$Settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -DontStopIfGoingOnBatteries `
  -AllowStartIfOnBatteries `
  -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
  -Description 'QuantCore 每週追蹤：建新快照 + 全策略回測，錯過起始時間會補跑。' -Force |
  Out-Null

Write-Host "已註冊排程：$TaskName（每週六 09:00，錯過補跑）"
Get-ScheduledTask -TaskName $TaskName | Format-List TaskName, State
