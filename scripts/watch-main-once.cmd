@echo off
REM Windows Task Scheduler wrapper for the local GitOps watcher (one pass).
REM Registered as task "DAAB-watch-main" to run every 2 minutes. See README/RELEASE-NOTES.
"C:\Program Files\Git\bin\bash.exe" -lc "cd /d/Projects/NewEcoSystem/DAAB && bash scripts/watch-main.sh --once >> .watch-main.log 2>&1"
