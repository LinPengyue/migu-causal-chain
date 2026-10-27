@echo off
setlocal
cd /d "%~dp0"
set "VENV=%cd%\.venv-api"
set "PORT=8000"

where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo 未找到 Python。请先安装 Python 3.9+ ：https://www.python.org/downloads/
  echo 安装时勾选 Add python.exe to PATH
  pause
  exit /b 1
)

if not exist "%VENV%\Scripts\python.exe" (
  echo 首次启动：创建虚拟环境并安装协议依赖…
  %PY% -m venv "%VENV%"
  "%VENV%\Scripts\python.exe" -m pip install -U pip
  "%VENV%\Scripts\python.exe" -m pip install -r "%cd%\requirements-api.txt"
  if errorlevel 1 (
    echo 依赖安装失败，请检查网络后重试。
    pause
    exit /b 1
  )
)

set "PYTHONPATH=%cd%\algo;%cd%"
echo 启动服务: http://127.0.0.1:%PORT%/docs
start "" "http://127.0.0.1:%PORT%/docs"
"%VENV%\Scripts\python.exe" -m uvicorn api.app:app --host 127.0.0.1 --port %PORT% --workers 1
pause
