@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting QQ Bot Bridge (ikun)...
python -u bridge.py >> logs\bridge.log 2>&1