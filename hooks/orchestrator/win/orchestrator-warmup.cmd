@echo off
rem SessionStart hook wrapper (Windows). Orchestrator warmup.
"%LOCALAPPDATA%\Programs\Python\Python314\python.exe" "%~dp0..\orchestrator-warmup.py"
exit /b 0
