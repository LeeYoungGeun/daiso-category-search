@echo off
REM === 서버 A (App) 배포 스크립트 ===
REM 서버 A (3.39.6.105) 에서 실행
REM
REM 사용법:
REM   start_server_live.bat          → .env 적용 + Docker 빌드 + 실행
REM   start_server_live.bat down     → 전체 중지
REM   start_server_live.bat logs     → 로그 보기
REM   start_server_live.bat restart  → 재시작

cd c:\Users\301\dev\daiso-category-search

IF "%1"=="down" (
    echo [APP] Stopping API + Frontend...
    docker compose -f infra/docker-compose.app.yml down
    exit /b
)

IF "%1"=="logs" (
    docker compose -f infra/docker-compose.app.yml logs -f
    exit /b
)

IF "%1"=="restart" (
    echo [APP] Restarting...
    docker compose -f infra/docker-compose.app.yml restart
    exit /b
)

echo [APP] Applying .env.live configuration...
copy /Y .env.live .env

echo [APP] Building and starting API + Frontend...
docker compose -f infra/docker-compose.app.yml up -d --build

echo.
echo [APP] Services started on Server A (3.39.6.105)
echo   - API:       http://localhost:8000
echo   - Frontend:  http://localhost:3000
echo   - Nginx:     호스트에서 직접 관리
echo.
echo [APP] Nginx 설정 적용:
echo   sudo cp infra/nginx-host.conf /etc/nginx/sites-available/daiso
echo   sudo ln -s /etc/nginx/sites-available/daiso /etc/nginx/sites-enabled/
echo   sudo nginx -t ^&^& sudo systemctl reload nginx
echo.
echo [APP] View logs: start_server_live.bat logs
echo [APP] Stop all:  start_server_live.bat down
