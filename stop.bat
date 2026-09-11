@echo off
chcp 65001 >nul
rem R11.5/M3：精确结束监听 127.0.0.1:8765 的进程，避免误杀 :18765 等相似端口
setlocal EnableDelayedExpansion
set FOUND=0
set PORT=8765

rem 优先 PowerShell 精确匹配本地端口
powershell -NoProfile -Command ^
  "$cs = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; foreach ($p in $cs) { if ($p) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue; Write-Output $p } }" > "%TEMP%\mtga_stop_pids.txt" 2>nul
if exist "%TEMP%\mtga_stop_pids.txt" (
  for /f %%a in (%TEMP%\mtga_stop_pids.txt) do (
    if not "%%a"=="" set FOUND=1
  )
  del "%TEMP%\mtga_stop_pids.txt" >nul 2>&1
)

if %FOUND%==1 (
  echo 面板服务已停止
) else (
  rem 回退：netstat 解析本地地址列，仅匹配 :8765 空格结尾（避免 18765）
  for /f "tokens=1,5" %%a in ('netstat -ano ^| findstr LISTENING') do (
    echo %%a | findstr /R /C:"[.:]8765$" >nul
    if not errorlevel 1 (
      taskkill /PID %%b /F >nul 2>&1
      if not errorlevel 1 set FOUND=1
    )
  )
  if !FOUND!==1 (
    echo 面板服务已停止
  ) else (
    echo 面板未在运行
  )
)
timeout /t 2 >nul
endlocal
