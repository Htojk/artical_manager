@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "scripts\start.py" %*
) else (
  python "scripts\start.py" %*
)
if errorlevel 1 (
  echo.
  echo 启动失败，请查看上方提示或 logs\ 目录下的日志。
  pause
)
endlocal
