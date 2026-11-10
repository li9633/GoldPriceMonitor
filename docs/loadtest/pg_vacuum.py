import os, sqlite3, statistics, sys, time
sys.path.insert(0, r"C:/Programer/GoldPriceMonitor/backend")
import pgserver, psycopg
from utils.time_utils import now

PG_DIR = os.path.join(os.getcwd(), "pgdata")

def bench(fn, repeat=6, warmup=2):
    for _ in range(warmup): fn()
    lat=[]
    for _ in range(repeat):
        t0=time.perf_counter(); fn(); lat.append((time.perf_counter()-t0)*1000)
    return statistics.median(lat)

srv = pgserver.get_server(PG_DIR, cleanup_mode="stop")
pg = psycopg.connect(srv.get_uri(), autocommit=True)
lite = sqlite3.connect("data/prices.db")
now_ts = int(now().timestamp()); cutoff = now_ts - 180*86400

print("VACUUM ANALYZE prices …")
t0=time.perf_counter()
with pg.cursor() as cur: cur.execute("VACUUM (ANALYZE) prices")
print(f"  耗时 {time.perf_counter()-t0:.1f}s\n")

sql_p = "SELECT MIN(price) FROM prices WHERE symbol = %s AND timestamp > %s"
def p_run():
    with pg.cursor() as cur:
        cur.execute(sql_p, ("gds_AUTD", cutoff)); cur.fetchall()
def l_run():
    lite.execute("SELECT MIN(price) FROM prices WHERE symbol = ? AND timestamp > ?", ("gds_AUTD", cutoff)).fetchall()

b = bench(p_run); a = bench(l_run)
print(f"VACUUM 后：SQLite {a:7.2f}ms   PG {b:7.2f}ms   PG 快 {a/b:.2f}×")
with pg.cursor() as cur:
    cur.execute("EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF) " + sql_p, ("gds_AUTD", cutoff))
    for r in cur.fetchall():
        if any(k in r[0] for k in ("Scan","Aggregate","Execution","Index")): print("    ", r[0])

print("\n强制关闭 seqscan，看 index-only scan 的真实上限：")
with pg.cursor() as cur:
    cur.execute("SET enable_seqscan=off")
    cur.execute("SET enable_bitmapscan=off")
b2 = bench(p_run)
with pg.cursor() as cur:
    cur.execute("EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF) " + sql_p, ("gds_AUTD", cutoff))
    for r in cur.fetchall():
        if any(k in r[0] for k in ("Scan","Aggregate","Execution","Index")): print("    ", r[0])
print(f"    强制 index-only：PG {b2:7.2f}ms  (SQLite {a:.2f}ms)")
lite.close(); pg.close(); srv.cleanup()
print("\nPG 已停止")
