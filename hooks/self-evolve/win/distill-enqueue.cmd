@echo off
rem SessionEnd hook wrapper (Windows). Same PATH prepend as distill-notify.
set "Path=%LOCALAPPDATA%\Programs\Python\Python314;%LOCALAPPDATA%\Programs\Python\Python314\Scripts;%Path%"
"%LOCALAPPDATA%\Programs\PortableGit\bin\bash.exe" -lc "~/.claude/hooks/self-evolve/distill-enqueue.sh"
exit /b 0
