#!/bin/bash
# === 서버 B (Search/Data) 배포 스크립트 ===
# 서버 B (54.180.1.204) 에서 실행
#
# 사용법:
#   chmod +x infra/start_data.sh
#   ./infra/start_data.sh          → 서비스 시작
#   ./infra/start_data.sh down     → 전체 중지
#   ./infra/start_data.sh logs     → 로그 보기
#   ./infra/start_data.sh status   → 상태 + 메모리 확인

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.data.yml"

case "${1:-up}" in
    down)
        echo "[DATA] Stopping ES + Qdrant + Redis..."
        docker compose -f "$COMPOSE_FILE" down
        ;;
    logs)
        docker compose -f "$COMPOSE_FILE" logs -f
        ;;
    status)
        echo "=== Docker Containers ==="
        docker compose -f "$COMPOSE_FILE" ps
        echo ""
        echo "=== System Memory ==="
        free -m
        echo ""
        echo "=== ES Cluster Health ==="
        curl -sf http://localhost:9200/_cluster/health?pretty 2>/dev/null || echo "ES not reachable"
        echo ""
        echo "=== ES JVM Heap ==="
        curl -sf http://localhost:9200/_nodes/stats/jvm?pretty 2>/dev/null | grep -A5 '"heap_used\|heap_max' || echo "ES not reachable"
        echo ""
        echo "=== Qdrant Health ==="
        curl -sf http://localhost:6333/healthz 2>/dev/null || echo "Qdrant not reachable"
        echo ""
        echo "=== Redis Info ==="
        redis-cli -h localhost info memory 2>/dev/null | grep "used_memory_human\|maxmemory_human" || echo "Redis not reachable"
        ;;
    up|*)
        # vm.max_map_count 설정 (ES 필수)
        echo "[DATA] Setting vm.max_map_count..."
        sudo sysctl -w vm.max_map_count=262144
        grep -q "vm.max_map_count" /etc/sysctl.conf || \
            echo "vm.max_map_count=262144" | sudo tee -a /etc/sysctl.conf

        echo "[DATA] Starting ES + Qdrant + Redis..."
        docker compose -f "$COMPOSE_FILE" up -d

        echo ""
        echo "[DATA] Services started on Server B (54.180.1.204)"
        echo "  - Elasticsearch:  :9200 (heap 512MB)"
        echo "  - Qdrant:         :6333"
        echo "  - Redis:          :6379"
        echo ""
        echo "[DATA] 방화벽 설정 (서버 A만 허용):"
        echo "  sudo ufw allow from 3.39.6.105 to any port 9200"
        echo "  sudo ufw allow from 3.39.6.105 to any port 6333"
        echo "  sudo ufw allow from 3.39.6.105 to any port 6379"
        echo "  sudo ufw enable"
        echo ""
        echo "[DATA] 상태 확인: $0 status"
        ;;
esac
