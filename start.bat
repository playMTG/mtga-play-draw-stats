@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set URL=http://127.0.0.1:8765

rem ---- 定位 Python：优先项目自带 .venv，无则首次运行自动创建 ----
if exist "%~dp0.venv\Scripts\python.exe" (
  set "PY=%~dp0.venv\Scripts\python.exe"
  goto :have_py
)
where python >nul 2>&1
if errorlevel 1 (
  echo [错误] 未找到 Python。请先安装 Python 3.11+ 并勾选 "Add to PATH"。
  pause
  exit /b 1
)
echo 首次运行：正在创建虚拟环境并安装依赖（约半分钟，仅一次）...
python -m venv .venv
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
if errorlevel 1 (
  echo [错误] 依赖安装失败，请检查网络后重试。
  pause
  exit /b 1
)
set "PY=%~dp0.venv\Scripts\python.exe"

:have_py
rem 已在运行？直接开浏览器
curl -s -o nul %URL%/api/status && (
  echo 面板已在运行，直接打开浏览器...
  start "" %URL%
  timeout /t 2 >nul
  exit /b 0
)

rem 后台最小化启动服务，等就绪后自动打开浏览器
echo 正在启动面板服务...
start "MTGA Panel" /min "%PY%" -m app.main
rem 等候上限放宽到 90 秒：历史日志累积较多时，启动后的回填需要更久
for /l %%i in (1,1,90) do (
  curl -s -o nul %URL%/api/status && goto :open
  timeout /t 1 /nobreak >nul
)
echo 90 秒内服务仍未就绪，请查看 data 目录下的日志
pause
exit /b 1

:open
start "" %URL%
echo 已在浏览器打开面板（http://127.0.0.1:8765）
echo 停止服务：双击 stop.bat，或关闭最小化的 "MTGA Panel" 窗口
timeout /t 5 >nul
