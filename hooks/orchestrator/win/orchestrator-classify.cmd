@echo off
rem UserPromptSubmit hook wrapper (Windows). Orchestrator complexity classifier.
"%LOCALAPPDATA%\Programs\Python\Python314\python.exe" "%~dp0..\orchestrator-classify.py"
exit /b 0
