@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting QBot v2.1...
python -u app.py >> logs\bridge.log 2>&1