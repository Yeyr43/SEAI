@echo off
setlocal
cd /d "%~dp0"
python "%~dp0seai_cli.py" %*
endlocal