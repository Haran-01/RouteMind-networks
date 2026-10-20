@echo off
setlocal
if defined ROUTEMIND_PYTHON goto execute
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" set "ROUTEMIND_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if defined ROUTEMIND_PYTHON goto execute
if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" set "ROUTEMIND_PYTHON=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if defined ROUTEMIND_PYTHON goto execute
echo Set ROUTEMIND_PYTHON to a real Python 3.10+ executable, then retry.
exit /b 1
:execute
"%ROUTEMIND_PYTHON%" "%~dp0scripts\cli.py" %*
exit /b %errorlevel%
