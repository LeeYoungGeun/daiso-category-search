@echo off
REM === Local Development Server ===
REM conda activate proj11 후 실행하세요
REM Docker 서비스 먼저: docker compose up -d

cd c:\Users\301\dev\daiso-category-search

echo [LOCAL] Applying .env.local configuration...
copy /Y .env.local .env

echo [LOCAL] Starting dev server (localhost:8000)...
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
