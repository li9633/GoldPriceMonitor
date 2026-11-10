"""公平化对比：给 PG 补上 INCLUDE 覆盖索引，再比一次 MIN / 24h 明细。

另外量化「优化前那个全表 COUNT(*) GROUP BY symbol」在两种引擎下的差异，
说明「以前 PG 能救、现在不需要」这个结论。
"""

import os
import sqlite3
import statistics
import sys
import time

sys.path.insert(0, r"C:\Programer\GoldPriceMonitor\backend")

import pgserver  # noqa: E402
import psycopg  # noqa: E402

from utils.time_utils import now  # noqa: E402

PG_DIR = os.path.join(os.getcwd(), "pgdata")


def bench(fn, repeat=6, warmup=2):
    for _ in range(warmup):
        fn()
    lat = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        lat.append((time.perf_counter() - t0) * 1000)
    return statistics.median(lat)


def show_plan(cur, sql, params):
    cur.execute("EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF) " + sql, params)
    for row in cur.fetchall():
        line = row[0]
        if any(k in line for k in ("Scan", "Aggregate", "Execution Time", "Index")):
            print(f"      {line}")


def main():
    now_ts = int(now().timestamp())
    cutoff_180 = now_ts - 180 * 86400
    cutoff_24 = now_ts - 86400

    srv = pgserver.get_server(PG_DIR, cleanup_mode="stop")
    pg = psycopg.connect(srv.get_uri())
    lite = sqlite3.connect("data/prices.db")

    print("=" * 76)
    print("给 PG 补覆盖索引：(symbol, timestamp) INCLUDE (price)")
    print("=" * 76)
    t0 = time.perf_counter()
    with pg.cursor() as cur:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_prices_cov "
                    "ON prices(symbol, timestamp) INCLUDE (price)")
    pg.commit()
    with pg.cursor() as cur:
        cur.execute("ANALYZE prices")
    pg.commit()
    print(f"  建索引 + ANALYZE 耗时 {time.perf_counter() - t0:.1f}s\n")

    cases = [
        ("未做预聚合：180 天 MIN(price)", cutoff_180),
        ("24h 明细（8640 行）", cutoff_24),
    ]
    for label, cutoff in cases:
        sql_l = ("SELECT MIN(price) FROM prices WHERE symbol = ? AND timestamp > ?"
                 if "MIN" in label else
                 "SELECT timestamp, price FROM prices WHERE symbol = ? AND timestamp > ? ORDER BY timestamp")
        sql_p = sql_l.replace("?", "%s")

        def l_run(sql_l=sql_l, cutoff=cutoff):
            lite.execute(sql_l, ("gds_AUTD", cutoff)).fetchall()

        def p_run(sql_p=sql_p, cutoff=cutoff):
            with pg.cursor() as cur:
                cur.execute(sql_p, ("gds_AUTD", cutoff))
                cur.fetchall()

        a, b = bench(l_run), bench(p_run)
        print(f"  {label:<32} SQLite {a:7.2f}ms   PG {b:7.2f}ms")
        with pg.cursor() as cur:
            show_plan(cur, sql_p, ("gds_AUTD", cutoff))
        pg.commit()

    print()
    print("=" * 76)
    print("优化前那个全表计数：SELECT symbol, COUNT(*) GROUP BY symbol")
    print("=" * 76)
    sql_l = "SELECT symbol, COUNT(*) FROM prices GROUP BY symbol ORDER BY 2 DESC"
    sql_p = sql_l

    def l_run():
        lite.execute(sql_l).fetchall()

    def p_run():
        with pg.cursor() as cur:
            cur.execute(sql_p)
            cur.fetchall()

    a, b = bench(l_run), bench(p_run, repeat=4)
    print(f"  SQLite {a:7.2f}ms   PG {b:7.2f}ms   （PG 快 {a / b:.1f}×）")
    print("  说明：这条正是优化前首页看板每 10 秒跑一次的那条（当时 332ms）。")
    print("        日线表上线后它已不存在，所以 PG 在这条上的优势已经没有意义。")

    lite.close()
    pg.close()
    srv.cleanup()
    print("\nPG 已停止")


if __name__ == "__main__":
    main()
