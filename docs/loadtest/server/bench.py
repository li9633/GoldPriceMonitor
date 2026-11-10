"""同一台 Ubuntu 服务器上：SQLite vs PostgreSQL 18 逐查询对比。

两边都用常驻连接、同一份数据、等价索引、都做过统计信息收集。
时间统一用 time.perf_counter() 包住「执行 + 取完结果集」，方法对称。
"""

import sqlite3
import statistics
import time

import psycopg2

SQLITE_DB = "perfdata/perf.db"
PG_DSN = "dbname=perf user=qb"


def pct(samples, p):
    ordered = sorted(samples)
    return ordered[min(int(len(ordered) * p / 100), len(ordered) - 1)]


def bench(fn, repeat=7, warmup=2):
    for _ in range(warmup):
        fn()
    lat = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        lat.append((time.perf_counter() - t0) * 1000)
    return statistics.median(lat), pct(lat, 95)


def main():
    lite = sqlite3.connect(SQLITE_DB)
    lite.execute("PRAGMA cache_size = -8000")
    pg = psycopg2.connect(PG_DSN)
    pgcur = pg.cursor()

    now_ts = int(time.time())
    day = lambda ts: (int(ts) // 86400) * 86400  # noqa: E731
    cutoff_24h = now_ts - 86400
    cutoff_90d = now_ts - 90 * 86400
    cutoff_180d = now_ts - 180 * 86400
    today = time.strftime("%Y-%m-%d", time.localtime(now_ts))
    tomorrow = time.strftime("%Y-%m-%d", time.localtime(now_ts + 86400))

    REVIEW = (
        "SELECT COUNT(*), "
        "COUNT(CASE WHEN price_t1 IS NOT NULL AND price_at_advice > 0 THEN 1 END), "
        "AVG(CASE WHEN price_t1 IS NOT NULL AND price_at_advice > 0 "
        "THEN (price_t1 - price_at_advice) / price_at_advice * 100 END), "
        "COUNT(CASE WHEN price_t7 IS NOT NULL AND price_at_advice > 0 THEN 1 END), "
        "AVG(CASE WHEN price_t7 IS NOT NULL AND price_at_advice > 0 "
        "THEN (price_t7 - price_at_advice) / price_at_advice * 100 END), "
        "COUNT(CASE WHEN price_t30 IS NOT NULL AND price_at_advice > 0 THEN 1 END), "
        "AVG(CASE WHEN price_t30 IS NOT NULL AND price_at_advice > 0 "
        "THEN (price_t30 - price_at_advice) / price_at_advice * 100 END) "
        "FROM advice_records"
    )

    cases = [
        ("快照 24h 明细（8640 行）",
         "SELECT timestamp, price FROM prices WHERE symbol = ? AND timestamp > ? ORDER BY timestamp",
         "SELECT timestamp, price FROM prices WHERE symbol = %s AND timestamp > %s ORDER BY timestamp",
         ("gds_AUTD", cutoff_24h)),
        ("MA 缓冲（最新 48 条）",
         "SELECT price FROM prices WHERE symbol = ? ORDER BY timestamp DESC LIMIT 48",
         "SELECT price FROM prices WHERE symbol = %s ORDER BY timestamp DESC LIMIT 48",
         ("gds_AUTD",)),
        ("日线 MIN（90 天最低价）",
         "SELECT MIN(low) FROM prices_daily WHERE symbol = ? AND day >= ?",
         "SELECT MIN(low) FROM prices_daily WHERE symbol = %s AND day >= %s",
         ("gds_AUTD", day(cutoff_90d))),
        ("最新价",
         "SELECT price FROM prices WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
         "SELECT price FROM prices WHERE symbol = %s ORDER BY timestamp DESC LIMIT 1",
         ("gds_AUTD",)),
        ("看板总记录数（日线 SUM）",
         "SELECT symbol, SUM(sample_count) FROM prices_daily GROUP BY symbol ORDER BY 2 DESC",
         "SELECT symbol, SUM(sample_count) FROM prices_daily GROUP BY symbol ORDER BY 2 DESC",
         ()),
        ("1 年图表（日线 366 行）",
         "SELECT day, price_sum / sample_count FROM prices_daily "
         "WHERE symbol = ? AND day >= ? AND day <= ? ORDER BY day",
         "SELECT day, price_sum / sample_count FROM prices_daily "
         "WHERE symbol = %s AND day >= %s AND day <= %s ORDER BY day",
         ("gds_AUTD", day(cutoff_90d), day(now_ts))),
        ("last_pushed（12 万行）",
         "SELECT * FROM advice_records WHERE symbol = ? AND status != ? ORDER BY id DESC LIMIT 1",
         "SELECT * FROM advice_records WHERE symbol = %s AND status <> %s ORDER BY id DESC LIMIT 1",
         ("gds_AUTD", "suppressed")),
        ("review_stats（12 万行条件聚合）", REVIEW, REVIEW, ()),
        ("top_failures（30 万行分组）",
         "SELECT error_type, COUNT(*) AS c, "
         "GROUP_CONCAT(DISTINCT SUBSTR(error_reason, 1, 100)) AS ex "
         "FROM notification_send_logs WHERE created_at >= ? AND created_at < ? "
         "AND success=0 AND error_type != '' GROUP BY error_type ORDER BY c DESC LIMIT 5",
         "SELECT error_type, COUNT(*) AS c, "
         "string_agg(DISTINCT left(error_reason, 100), ',') AS ex "
         "FROM notification_send_logs WHERE created_at >= %s AND created_at < %s "
         "AND success=0 AND error_type <> '' GROUP BY error_type ORDER BY c DESC LIMIT 5",
         (today, tomorrow)),
        ("当天通知计数（30 万行）",
         "SELECT COUNT(*), COALESCE(SUM(success),0) FROM notification_send_logs "
         "WHERE created_at >= ? AND created_at < ?",
         "SELECT COUNT(*), COALESCE(SUM(success),0) FROM notification_send_logs "
         "WHERE created_at >= %s AND created_at < %s",
         (today, tomorrow)),
        ("全表 COUNT(*)",
         "SELECT COUNT(*) FROM prices WHERE symbol = ?",
         "SELECT COUNT(*) FROM prices WHERE symbol = %s",
         ("gds_AUTD",)),
        ("[优化前] 180 天 MIN(price)",
         "SELECT MIN(price) FROM prices WHERE symbol = ? AND timestamp > ?",
         "SELECT MIN(price) FROM prices WHERE symbol = %s AND timestamp > %s",
         ("gds_AUTD", cutoff_180d)),
        ("[优化前] COUNT(*) GROUP BY symbol",
         "SELECT symbol, COUNT(*) FROM prices GROUP BY symbol ORDER BY 2 DESC",
         "SELECT symbol, COUNT(*) FROM prices GROUP BY symbol ORDER BY 2 DESC",
         ()),
    ]

    print(f"{'查询':<34} {'SQLite':>11} {'PG 18':>11}  {'谁快':>10}")
    print("-" * 72)
    rows = []
    for label, lsql, psql, params in cases:
        def run_l(sql=lsql, ps=params):
            lite.execute(sql, ps).fetchall()

        def run_p(sql=psql, ps=params):
            pgcur.execute(sql, ps)
            pgcur.fetchall()

        a, _ = bench(run_l)
        b, _ = bench(run_p)
        if b == 0:
            verdict = "—"
        elif a >= b:
            verdict = f"PG {a / b:.1f}×"
        else:
            verdict = f"SQLite {b / a:.1f}×"
        print(f"{label:<34} {a:>9.2f}ms {b:>9.2f}ms  {verdict:>10}")
        rows.append((label, a, b))

    print()
    print("=== 连接开销（每次新建连接 + 一次查询）===")

    def lite_conn():
        c = sqlite3.connect(SQLITE_DB)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("SELECT price FROM prices WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
                  ("gds_AUTD",)).fetchall()
        c.close()

    def pg_conn():
        c = psycopg2.connect(PG_DSN)
        cur = c.cursor()
        cur.execute("SELECT price FROM prices WHERE symbol=%s "
                    "ORDER BY timestamp DESC LIMIT 1", ("gds_AUTD",))
        cur.fetchall()
        cur.close()
        c.close()

    a, _ = bench(lite_conn, repeat=15)
    b, _ = bench(pg_conn, repeat=15)
    print(f"{'SQLite（文件连接 + PRAGMA + 查询）':<34} {a:>9.2f}ms")
    print(f"{'PG（unix socket 连接 + 查询）':<34} {b:>9.2f}ms")

    print()
    print("=== PG 关键执行计划（确认走的是索引不是全表扫）===")
    for label, sql, params in (
        ("日线 MIN", "SELECT MIN(low) FROM prices_daily WHERE symbol = %s AND day >= %s",
         ("gds_AUTD", day(cutoff_90d))),
        ("top_failures",
         "SELECT error_type, COUNT(*) FROM notification_send_logs "
         "WHERE created_at >= %s AND created_at < %s AND success=0 AND error_type <> '' "
         "GROUP BY error_type ORDER BY 2 DESC LIMIT 5", (today, tomorrow)),
        ("[优化前] 180 天 MIN",
         "SELECT MIN(price) FROM prices WHERE symbol = %s AND timestamp > %s",
         ("gds_AUTD", cutoff_180d)),
    ):
        pgcur.execute("EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF) " + sql, params)
        plan = [r[0] for r in pgcur.fetchall()]
        print(f"  [{label}]")
        for line in plan:
            if any(k in line for k in ("Scan", "Aggregate", "Execution")):
                print(f"     {line.strip()}")

    pgcur.close()
    pg.close()
    lite.close()


if __name__ == "__main__":
    main()
