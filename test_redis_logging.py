"""Quick Redis log test — writes output to file to avoid terminal buffering"""
import logging
import os
import sys
from pathlib import Path

outfile = open("test_redis_output.txt", "w", encoding="utf-8")

class FileHandler(logging.Handler):
    def emit(self, record):
        outfile.write(self.format(record) + "\n")
        outfile.flush()

handler = FileHandler()
handler.setFormatter(logging.Formatter("%(levelname)-7s %(name)s: %(message)s"))
logging.root.addHandler(handler)
logging.root.setLevel(logging.DEBUG)

sys.path.insert(0, str(Path(__file__).parent))
from backend.search import cache as cache_mod

def w(msg):
    outfile.write(msg + "\n")
    outfile.flush()

# Test 1: Redis UP
cache_mod._redis_available = None
cache_mod._redis_client = None
w("=" * 50)
w("TEST 1: Redis UP (Docker running)")
w("=" * 50)
h = cache_mod.cache_health()
w(f"Health: {h}")
cache_mod.cache_set("test", "log_verify", {"v": 1}, ttl=30)
v = cache_mod.cache_get("test", "log_verify")
w(f"Get HIT: {v}")
v2 = cache_mod.cache_get("test", "missing_key_xyz")
w(f"Get MISS: {v2}")

# Test 2: Redis DOWN (simulated via flag)
w("")
w("=" * 50)
w("TEST 2: Redis DOWN (simulated)")
w("=" * 50)
cache_mod._redis_available = False
cache_mod._redis_client = None
h2 = cache_mod.cache_health()
w(f"Health: {h2}")
ok = cache_mod.cache_set("test", "key", {"v": 1})
w(f"Set result: {ok}")
v3 = cache_mod.cache_get("test", "key")
w(f"Get result: {v3}")
w("")
w("DONE — no exceptions raised, graceful degradation confirmed")

outfile.close()
