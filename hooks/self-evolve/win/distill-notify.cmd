@echo off
rem SessionStart hook wrapper (Windows). Puts Python first on PATH so git-bash's python3 resolves
rem to the real interpreter (avoids the Microsoft Store alias stub).
set "Path=%LOCALAPPDATA%\Programs\Python\Python314;%LOCALAPPDATA%\Programs\Python\Python314\Scripts;%Path%"
"%LOCALAPPDATA%\Programs\PortableGit\bin\bash.exe" -lc "~/.claude/hooks/self-evolve/distill-notify.sh"
exit /b 0
