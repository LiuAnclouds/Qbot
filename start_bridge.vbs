' QQ Bot Bridge - 开机自启动 VBS 脚本
' 无窗口后台运行

Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")

scriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)
batPath = scriptDir & "\start_bridge.bat"
logDir = scriptDir & "\logs"

' 创建日志目录
If Not FSO.FolderExists(logDir) Then
    FSO.CreateFolder(logDir)
End If

' 隐藏窗口运行
WshShell.Run """" & batPath & """", 0, False