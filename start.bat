@echo off
rem LedgerFuse - 从源码一键启动（纯本地，数据存在 backend\data\bills.db）
rem 想要独立可执行文件请直接从 Releases 下载 LedgerFuse-windows-x64.zip
cd /d "%~dp0backend"
start "" http://127.0.0.1:8000
python -m uvicorn app.main:app --port 8000
