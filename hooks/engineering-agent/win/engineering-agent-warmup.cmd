@echo off
rem SessionStart hook wrapper (Windows). Engineering Agent warmup.
"%LOCALAPPDATA%\Programs\Python\Python314\python.exe" "%~dp0..\engineering-agent-warmup.py"
exit /b 0
