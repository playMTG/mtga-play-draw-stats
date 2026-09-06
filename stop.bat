@echo off
chcp 65001 >nul
rem 找到占用 8765 端口的进程并结束
set FOUND=0
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :8765 ^| findstr LISTENING') do (
  taskkill /PID %%p /F >nul 2>&1
  set FOUND=1
)
if %FOUND%==1 (
  echo 面板服务已停止
) else (
  echo 面板未在运行
)
timeout /t 2 >nul
