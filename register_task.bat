@echo off
chcp 65001 >nul
rem 一键注册任务计划：登录自启 + 崩溃自动重启 + 无窗口后台运行
rem 只需运行一次。注册后 start.bat/stop.bat 仍可用于手动启停。
rem 前提：先运行一次 start.bat（它会创建 .venv 并装好依赖）。

if not exist "%~dp0.venv\Scripts\pythonw.exe" (
  echo [错误] 未找到 .venv，请先双击运行一次 start.bat 完成初始化。
  pause
  exit /b 1
)
set "PYW=%~dp0.venv\Scripts\pythonw.exe"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$a = New-ScheduledTaskAction -Execute '%PYW%' -Argument '-m app.main' -WorkingDirectory '%~dp0';" ^
  "$t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME;" ^
  "$s = New-ScheduledTaskSettingsSet -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries;" ^
  "Register-ScheduledTask -TaskName 'MTGA_Panel' -Action $a -Trigger $t -Settings $s -Force"

echo.
echo 注册完成。重启电脑后面板将自动运行（崩溃也会 1 分钟内自动重启）。
echo 如需立即启动，请运行：start.bat
pause
