#!/bin/bash
# === 서버 B 메모리/Swap 모니터링 ===
# 서버 B (54.180.1.204) 에서 실행
#
# 사용법:
#   chmod +x infra/monitor.sh
#   ./infra/monitor.sh              → 한 번 실행
#   watch -n 5 ./infra/monitor.sh   → 5초 간격 반복
#
# cron 등록 (10분마다 로그 기록):
#   */10 * * * * /path/to/infra/monitor.sh >> /var/log/daiso-monitor.log 2>&1

set -e

echo "===== $(date '+%Y-%m-%d %H:%M:%S') ====="

# ── 시스템 메모리 ──
echo ""
echo "── System Memory ──"
free -m | awk 'NR==1{print $0} NR==2{
    used=$3; total=$2; pct=used/total*100;
    printf "%s %6dMB / %6dMB (%.1f%%)\n", $1, used, total, pct
} NR==3{
    used=$3;
    if(used > 0) printf "Swap:  %6dMB used ⚠️\n", used
    else printf "Swap:  none ✅\n"
}'

# ── ES Heap ──
echo ""
echo "── Elasticsearch JVM Heap ──"
ES_STATS=$(curl -sf http://localhost:9200/_nodes/stats/jvm 2>/dev/null)
if [ $? -eq 0 ]; then
    echo "$ES_STATS" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for node_id, node in data.get('nodes', {}).items():
    heap = node['jvm']['mem']
    used = heap['heap_used_in_bytes'] / 1024 / 1024
    max_h = heap['heap_max_in_bytes'] / 1024 / 1024
    pct = heap['heap_used_percent']
    status = '⚠️' if pct > 85 else '✅'
    print(f'  Heap: {used:.0f}MB / {max_h:.0f}MB ({pct}%) {status}')
" 2>/dev/null || echo "  Parse error"
else
    echo "  ❌ ES not reachable"
fi

# ── Qdrant ──
echo ""
echo "── Qdrant ──"
QD_HEALTH=$(curl -sf http://localhost:6333/healthz 2>/dev/null)
if [ $? -eq 0 ]; then
    echo "  Status: ✅ healthy"
    # 컬렉션 정보
    curl -sf http://localhost:6333/collections 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
for c in data.get('result', {}).get('collections', []):
    print(f\"  Collection: {c['name']}\")
" 2>/dev/null || true
else
    echo "  ❌ Qdrant not reachable"
fi

# ── Redis ──
echo ""
echo "── Redis ──"
REDIS_INFO=$(redis-cli -h localhost info memory 2>/dev/null)
if [ $? -eq 0 ]; then
    USED=$(echo "$REDIS_INFO" | grep "used_memory_human" | head -1 | tr -d '\r' | cut -d: -f2)
    MAX=$(echo "$REDIS_INFO" | grep "maxmemory_human" | tr -d '\r' | cut -d: -f2)
    echo "  Used: $USED / Max: $MAX ✅"
else
    echo "  ❌ Redis not reachable"
fi

# ── Docker 컨테이너 리소스 ──
echo ""
echo "── Docker Container Stats ──"
docker stats --no-stream --format "  {{.Name}}: CPU {{.CPUPerc}} / Mem {{.MemUsage}}" \
    daiso-elasticsearch daiso-qdrant daiso-redis 2>/dev/null || echo "  Docker stats unavailable"

echo ""
echo "============================="
