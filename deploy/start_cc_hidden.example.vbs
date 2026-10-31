' Launch cc-connect without a console window.
' Copy this file next to start_cc.bat in %USERPROFILE%\.cc-connect.
Set sh = CreateObject("WScript.Shell")
path = sh.ExpandEnvironmentStrings("%USERPROFILE%") & "\.cc-connect\start_cc.bat"
sh.Run "cmd.exe /c """ & path & """", 0, False
