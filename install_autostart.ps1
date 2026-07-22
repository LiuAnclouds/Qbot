# QQ Bot Bridge - Windows Task Scheduler 自启动设置
# 以管理员身份运行此脚本注册开机自启

$taskName = "QQBotBridge"
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$batPath = "$scriptPath\start_bridge.bat"

# 删除已有任务
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# 创建新任务 (开机自启, 隐藏窗口, 失败后自动重启)
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$scriptPath\start_bridge.vbs`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "QQ Bot Bridge (ikun) - 开机自启动"

Write-Host "✅ 开机自启动已注册! 任务名: $taskName"
Write-Host "管理命令:"
Write-Host "  启动: Start-ScheduledTask -TaskName '$taskName'"
Write-Host "  停止: Stop-ScheduledTask -TaskName '$taskName'"
Write-Host "  删除: Unregister-ScheduledTask -TaskName '$taskName'"
Write-Host "  查看: Get-ScheduledTask -TaskName '$taskName'"