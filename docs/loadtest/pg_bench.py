"""同一份 630 万行数据：SQLite vs PostgreSQL 16 实测对比。

只比较「改完之后剩下的真实查询」，不比较已经用日线表消掉的东西
（那样对两者都不公平，也不反映现状）。

关键公平性处理：
  - 两边都用**常驻连接**测量纯查询耗时（排除连接建立开销）；
  - 连接开销单独测；
  - PG 与 SQLite 都建等价索引、都执行统计信息更新（ANALYZE）。
"""

import os
import random
import sqlite3
import statistics
import sys
import time
from contextlib import contextmanager

sys.path.insert(0, r"C:\Programer\GoldPriceMonitor\backend")

import pgserver  # noqa: E402
import psycopg  # noqa: E402

from mapper.price_mapper import _day_bucket  # noqa: E402
from utils.time_utils import now  # noqa: E402

SQLITE_DB = "data/prices.db"
PORT_DB = "data/portfolio.db"
SETTINGS_DB = "data/system_settings.db"
MODEL_DB = "data/model_pool.db"
PG_DIR = os.path.join(os.getcwd(), "pgdata")
ROWS = 1_000_000  # 抽样上限，用于「大表全扫」类查询的对照（0 = 全量）

RESULTS = []
_SRV = None


def pct(samples, p):
    ordered = sorted(samples)
    return ordered[min(int(len(ordered) * p / 100), len(ordered) - 1)]


def bench(label, fn, repeat=8, warmup=2):
    for _ in range(warmup):
        fn()
    lat = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        lat.append((time.perf_counter() - t0) * 1000)
    return {"label": label, "p50": statistics.median(lat), "p95": pct(lat, 95)}


def section(t):
    print(f"\n{'=' * 76}\n{t}\n{'=' * 76}", flush=True)


# ==================== PG 初始化 ====================

DDL = """
DROP TABLE IF EXISTS prices;
CREATE TABLE prices (
    id        bigint,
    timestamp bigint NOT NULL,
    symbol    text,
    price     double precision
);
DROP TABLE IF EXISTS prices_daily;
CREATE TABLE prices_daily (
    symbol       text NOT NULL,
    day          bigint NOT NULL,
    high         double precision NOT NULL,
    low          double precision NOT NULL,
    price_sum    double precision NOT NULL,
    sample_count integer NOT NULL,
    PRIMARY KEY (symbol, day)
);
DROP TABLE IF EXISTS advice_records;
CREATE TABLE advice_records (
    id              bigint PRIMARY KEY,
    created_at      text NOT NULL,
    kind            text NOT NULL,
    action          text NOT NULL,
    symbol          text NOT NULL,
    status          text NOT NULL,
    price_at_advice double precision,
    price_t1        double precision,
    price_t7        double precision,
    price_t30       double precision
);
DROP TABLE IF EXISTS notification_send_logs;
CREATE TABLE notification_send_logs (
    id           bigint,
    symbol       text,
    success      integer NOT NULL,
    error_type   text NOT NULL DEFAULT '',
    error_reason text NOT NULL DEFAULT '',
    created_at   text NOT NULL
);
DROP TABLE IF EXISTS ai_logs_text;
CREATE TABLE ai_logs_text (
    id            bigint,
    call_time     text NOT NULL,
    success       integer NOT NULL,
    from_cache    integer NOT NULL DEFAULT 0,
    total_tokens  integer NOT NULL DEFAULT 0
);
DROP TABLE IF EXISTS ai_logs_ts;
CREATE TABLE ai_logs_ts (
    id            bigint,
    call_time     timestamptz NOT NULL,
    success       integer NOT NULL,
    from_cache    integer NOT NULL DEFAULT 0,
    total_tokens  integer NOT NULL DEFAULT 0
);
"""

INDEXES = """
CREATE INDEX idx_prices_symbol_ts ON prices(symbol, timestamp);
CREATE INDEX idx_prices_symbol_ts_price ON prices(symbol, timestamp, price);
CREATE INDEX idx_advice_symbol_id_desc ON advice_records(symbol, id DESC);
CREATE INDEX idx_notify_created ON notification_send_logs(created_at);
CREATE INDEX idx_notify_success ON notification_send_logs(success);
CREATE INDEX idx_ai_text_time ON ai_logs_text(call_time);
CREATE INDEX idx_ai_ts_time ON ai_logs_ts(call_time);
"""


def sqlite_rows(db, sql, params=(), batch=50000):
    conn = sqlite3.connect(db)
    try:
        cur = conn.execute(sql, params)
        while True:
            rows = cur.fetchmany(batch)
            if not rows:
                break
            yield rows
    finally:
        conn.close()


def load_all(pg):
    with pg.cursor() as cur:
        cur.execute(DDL)
    pg.commit()

    jobs = [
        ("prices", SQLITE_DB,
         "SELECT id, timestamp, symbol, price FROM prices",
         "COPY prices (id, timestamp, symbol, price) FROM STDIN"),
        ("prices_daily", SQLITE_DB,
         "SELECT symbol, day, high, low, price_sum, sample_count FROM prices_daily",
         "COPY prices_daily (symbol, day, high, low, price_sum, sample_count) FROM STDIN"),
        ("advice_records", PORT_DB,
         "SELECT id, created_at, kind, action, symbol, status, price_at_advice, "
         "price_t1, price_t7, price_t30 FROM advice_records",
         "COPY advice_records (id, created_at, kind, action, symbol, status, "
         "price_at_advice, price_t1, price_t7, price_t30) FROM STDIN"),
        ("notification_send_logs", SETTINGS_DB,
         "SELECT id, symbol, success, error_type, error_reason, created_at "
         "FROM notification_send_logs",
         "COPY notification_send_logs (id, symbol, success, error_type, error_reason, "
         "created_at) FROM STDIN"),
    ]
    for name, db, sql, copy_sql in jobs:
        t0 = time.perf_counter()
        total = 0
        with pg.cursor() as cur:
            with cur.copy(copy_sql) as copy:
                for batch in sqlite_rows(db, sql):
                    for row in batch:
                        copy.write_row(row)
                        total += 1
        pg.commit()
        print(f"  {name:<24} {total:>9,} 行  {time.perf_counter() - t0:5.1f}s", flush=True)

    # AI 日志两种时间类型各一份（用于比较 text vs timestamptz）
    t0 = time.perf_counter()
    src = sqlite3.connect(MODEL_DB).execute(
        "SELECT id, call_time, success, from_cache, total_tokens FROM ai_call_logs"
    ).fetchall()
    for table in ("ai_logs_text", "ai_logs_ts"):
        with pg.cursor() as cur:
            with cur.copy(f"COPY {table} (id, call_time, success, from_cache, total_tokens) "
                          "FROM STDIN") as copy:
                for r in src:
                    copy.write_row(r)
        pg.commit()
        print(f"  {table:<24} {len(src):>9,} 行", flush=True)
    print(f"  AI 日志导入合计 {time.perf_counter() - t0:.1f}s", flush=True)

    t0 = time.perf_counter()
    with pg.cursor() as cur:
        cur.execute(INDEXES)
    pg.commit()
    print(f"  建索引 {time.perf_counter() - t0:.1f}s", flush=True)
    t0 = time.perf_counter()
    with pg.cursor() as cur:
        cur.execute("ANALYZE")
    pg.commit()
    print(f"  ANALYZE {time.perf_counter() - t0:.1f}s", flush=True)


# ==================== 查询对 ====================

def build_cases(cutoff_24h, cutoff_90d, day_lo, day_hi, today_start, tomorrow_start):
    """(名称, 所属 SQLite 库, SQLite SQL, PG SQL, 参数) —— 同一语义、各自方言"""
    P, S = SQLITE_DB, SETTINGS_DB
    return [
        (
            "快照 24h 明细（8640 行）", P,
            "SELECT timestamp, price FROM prices WHERE symbol = ? AND timestamp > ? ORDER BY timestamp",
            "SELECT timestamp, price FROM prices WHERE symbol = %s AND timestamp > %s ORDER BY timestamp",
            ("gds_AUTD", cutoff_24h),
        ),
        (
            "MA 缓冲（最新 48 条）", P,
            "SELECT price FROM prices WHERE symbol = ? ORDER BY timestamp DESC LIMIT 48",
            "SELECT price FROM prices WHERE symbol = %s ORDER BY timestamp DESC LIMIT 48",
            ("gds_AUTD",),
        ),
        (
            "日线 MIN（90 天最低价）", P,
            "SELECT MIN(low) FROM prices_daily WHERE symbol = ? AND day >= ?",
            "SELECT MIN(low) FROM prices_daily WHERE symbol = %s AND day >= %s",
            ("gds_AUTD", _day_bucket(cutoff_90d)),
        ),
        (
            "最新价", P,
            "SELECT price FROM prices WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
            "SELECT price FROM prices WHERE symbol = %s ORDER BY timestamp DESC LIMIT 1",
            ("gds_AUTD",),
        ),
        (
            "看板总记录数（日线 SUM）", P,
            "SELECT symbol, SUM(sample_count) FROM prices_daily GROUP BY symbol ORDER BY 2 DESC",
            "SELECT symbol, SUM(sample_count) FROM prices_daily GROUP BY symbol ORDER BY 2 DESC",
            (),
        ),
        (
            "1 年图表（日线 366 行）", P,
            "SELECT day, price_sum / sample_count FROM prices_daily "
            "WHERE symbol = ? AND day >= ? AND day <= ? ORDER BY day",
            "SELECT day, price_sum / sample_count FROM prices_daily "
            "WHERE symbol = %s AND day >= %s AND day <= %s ORDER BY day",
            ("gds_AUTD", day_lo, day_hi),
        ),
        (
            "last_pushed（12 万行表）", PORT_DB,
            "SELECT * FROM advice_records WHERE symbol = ? AND status != ? "
            "ORDER BY id DESC LIMIT 1",
            "SELECT * FROM advice_records WHERE symbol = %s AND status <> %s "
            "ORDER BY id DESC LIMIT 1",
            ("gds_AUTD", "suppressed"),
        ),
        (
            "review_stats（单遍条件聚合 12 万行）", PORT_DB,
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
            "FROM advice_records",
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
            "FROM advice_records",
            (),
        ),
        (
            "top_failures（30 万行分组）", S,
            "SELECT error_type, COUNT(*) AS c, "
            "GROUP_CONCAT(DISTINCT SUBSTR(error_reason, 1, 100)) AS ex "
            "FROM notification_send_logs "
            "WHERE created_at >= ? AND created_at < ? AND success=0 AND error_type != '' "
            "GROUP BY error_type ORDER BY c DESC LIMIT 5",
            "SELECT error_type, COUNT(*) AS c, "
            "string_agg(DISTINCT left(error_reason, 100), ',') AS ex "
            "FROM notification_send_logs "
            "WHERE created_at >= %s AND created_at < %s AND success=0 AND error_type <> '' "
            "GROUP BY error_type ORDER BY c DESC LIMIT 5",
            (today_start, tomorrow_start),
        ),
        (
            "当天通知计数（30 万行表，索引范围）", S,
            "SELECT COUNT(*), COALESCE(SUM(success),0) FROM notification_send_logs "
            "WHERE created_at >= ? AND created_at < ?",
            "SELECT COUNT(*), COALESCE(SUM(success),0) FROM notification_send_logs "
            "WHERE created_at >= %s AND created_at < %s",
            (today_start, tomorrow_start),
        ),
        (
            "全表 COUNT(*)（未优化的 /prices/count）", P,
            "SELECT COUNT(*) FROM prices WHERE symbol = ?",
            "SELECT COUNT(*) FROM prices WHERE symbol = %s",
            ("gds_AUTD",),
        ),
        (
            "对照：未做预聚合时的 180 天 MIN", P,
            "SELECT MIN(price) FROM prices WHERE symbol = ? AND timestamp > ?",
            "SELECT MIN(price) FROM prices WHERE symbol = %s AND timestamp > %s",
            ("gds_AUTD", cutoff_90d * 2),
        ),
    ]


def main():
    section("0. 启动 PostgreSQL 并导入同一份数据")
    global _SRV
    t0 = time.perf_counter()
    srv = pgserver.get_server(PG_DIR, cleanup_mode="stop")
    _SRV = srv
    print(f"  PG 启动 {time.perf_counter() - t0:.1f}s  {srv.get_uri()}")
    pg = psycopg.connect(srv.get_uri(), autocommit=False)
    with pg.cursor() as cur:
        cur.execute("SHOW server_version")
        ver = cur.fetchone()[0]
        cur.execute("SHOW max_parallel_workers_per_gather")
        par = cur.fetchone()[0]
        cur.execute("SHOW shared_buffers")
        sb = cur.fetchone()[0]
    pg.commit()
    print(f"  PostgreSQL {ver} / 并行度 {par} / shared_buffers {sb}")

    with pg.cursor() as cur:
        cur.execute("SELECT to_regclass('public.prices') IS NOT NULL")
        ready = cur.fetchone()[0]
    pg.commit()
    if ready:
        with pg.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM prices")
            n = cur.fetchone()[0]
        pg.commit()
        print(f"  复用已导入的数据（prices {n:,} 行），跳过导入")
    else:
        load_all(pg)

    section("1. 逐查询对比（常驻连接，纯查询耗时）")
    now_ts = int(now().timestamp())
    cutoff_24h = now_ts - 86400
    cutoff_90d = now_ts - 90 * 86400
    today_start = time.strftime("%Y-%m-%d", time.localtime(now_ts))
    tomorrow_start = time.strftime(
        "%Y-%m-%d", time.localtime(now_ts + 86400)
    )

    lite_conns = {
        SQLITE_DB: sqlite3.connect(SQLITE_DB),
        PORT_DB: sqlite3.connect(PORT_DB),
        SETTINGS_DB: sqlite3.connect(SETTINGS_DB),
    }
    cases = build_cases(
        cutoff_24h, cutoff_90d, _day_bucket(cutoff_90d), _day_bucket(now_ts),
        today_start, tomorrow_start,
    )

    print(f"{'查询':<38} {'SQLite':>10} {'PG':>10} {'倍数':>8}")
    print("-" * 70)
    for label, db, lsql, psql, params in cases:
        lite = lite_conns[db]

        def run_lite(sql=lsql, params=params, lite=lite):
            lite.execute(sql, params).fetchall()

        def run_pg(sql=psql, params=params):
            with pg.cursor() as cur:
                cur.execute(sql, params)
                cur.fetchall()

        a = bench(label, run_lite)
        b = bench(label, run_pg)
        ratio = a["p50"] / b["p50"] if b["p50"] else float("inf")
        verdict = f"{ratio:6.1f}×" if ratio >= 1 else f"{ratio:5.2f}×"
        print(f"{label:<38} {a['p50']:>8.2f}ms {b['p50']:>8.2f}ms {verdict:>8}")
        RESULTS.append((label, a["p50"], b["p50"]))
    for conn in lite_conns.values():
        conn.close()

    section("2. 连接开销（这是应用真实付出的一部分）")
    def lite_connect_query():
        conn = sqlite3.connect(SQLITE_DB, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA cache_size = -8000")
        conn.execute("SELECT price FROM prices WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
                     ("gds_AUTD",)).fetchall()
        conn.close()

    def pg_new_connection():
        c = psycopg.connect(srv.get_uri())
        with c.cursor() as cur:
            cur.execute("SELECT price FROM prices WHERE symbol=%s ORDER BY timestamp DESC LIMIT 1",
                        ("gds_AUTD",))
            cur.fetchall()
        c.close()

    a = bench("每次新建连接 + 查询", lite_connect_query)
    b = bench("每次新建连接 + 查询", pg_new_connection)
    print(f"{'SQLite（新建连接+PRAGMA+查询）':<38} {a['p50']:>8.2f}ms")
    print(f"{'PG（新建 TCP 连接+查询）':<38} {b['p50']:>8.2f}ms")
    print("  注：两边生产实现都会用连接池，此项只用于说明「每查询新建连接」的真实代价")

    section("3. 文本时间列 vs timestamptz（AI 统计的「今天」聚合）")
    for table, col in (("ai_logs_text", "call_time"), ("ai_logs_ts", "call_time")):
        if table == "ai_logs_text":
            sql = (f"SELECT COUNT(*), COALESCE(SUM(success),0), COALESCE(SUM(from_cache),0), "
                   f"COALESCE(SUM(total_tokens),0) FROM {table} "
                   f"WHERE {col} >= %s AND {col} < %s")
            params = (today_start, tomorrow_start)
        else:
            sql = (f"SELECT COUNT(*), COALESCE(SUM(success),0), COALESCE(SUM(from_cache),0), "
                   f"COALESCE(SUM(total_tokens),0) FROM {table} "
                   f"WHERE {col} >= date_trunc('day', now()) "
                   f"AND {col} < date_trunc('day', now()) + interval '1 day'")
            params = ()

        def run(sql=sql, params=params):
            with pg.cursor() as cur:
                cur.execute(sql, params)
                cur.fetchall()

        r = bench(table, run)
        with pg.cursor() as cur:
            cur.execute("EXPLAIN (COSTS OFF) " + sql, params)
            plan = " / ".join(row[0] for row in cur.fetchall())
        pg.commit()
        print(f"  {table:<18} p50={r['p50']:6.2f}ms   {plan[:90]}")

    def lite_today():
        conn = sqlite3.connect(MODEL_DB)
        conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(success),0), COALESCE(SUM(from_cache),0), "
            "COALESCE(SUM(total_tokens),0) FROM ai_call_logs "
            "WHERE call_time >= ? AND call_time < ?",
            (today_start, tomorrow_start),
        ).fetchall()
        conn.close()

    r = bench("SQLite（同样语义）", lite_today)
    print(f"  {'SQLite 对照':<18} p50={r['p50']:6.2f}ms")

    section("汇总")
    print(f"{'查询':<38} {'SQLite':>10} {'PG':>10}")
    for label, a, b in sorted(RESULTS, key=lambda x: -x[1]):
        print(f"{label:<38} {a:>8.2f}ms {b:>8.2f}ms")

    pg.close()


def run():
    try:
        main()
    finally:
        if _SRV is not None:
            try:
                _SRV.cleanup()
                print("\nPG 已停止")
            except Exception as exc:  # noqa: BLE001
                print(f"\n停止 PG 失败：{exc}")


if __name__ == "__main__":
    run()
