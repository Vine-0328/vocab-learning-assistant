@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "dist\VocabAssistant.exe" (
    start "" "dist\VocabAssistant.exe"
    exit /b
)
where py >nul 2>nul
if not errorlevel 1 (
    py -3 vocab_learner.py
    if errorlevel 1 pause
    exit /b
)
where python >nul 2>nul
if not errorlevel 1 (
    python vocab_learner.py
    if errorlevel 1 pause
    exit /b
)
echo 请使用已打包的 VocabAssistant.exe，或先安装 Python 3.10 以上版本。
pause
