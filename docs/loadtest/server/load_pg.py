"""把 gen.py 产出的 CSV 装进 PostgreSQL，建与 SQLite 完全等价的索引。

用法：python3 load_pg.py
"""

import time

import psycopg2

DSN = "dbname=perf user=qb"
DATA = "perfdata"

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
    id           bigint PRIMARY KEY,
    symbol       text,
    success      integer NOT NULL,
    error_type   text NOT NULL DEFAULT '',
    error_reason text NOT NULL DEFAULT '',
    created_at   text NOT NULL
);
DROP TABLE IF EXISTS ai_call_logs;
CREATE TABLE ai_call_logs (
    id           bigint PRIMARY KEY,
    call_time    text NOT NULL,
    success      integer NOT NULL,
    from_cache   integer NOT NULL DEFAULT 0,
    total_tokens integer NOT NULL DEFAULT 0
);
"""

LOADS = [
    ("prices.csv", "COPY prices (id, timestamp, symbol, price) FROM STDIN WITH (FORMAT csv)"),
    ("prices_daily.csv",
     "COPY prices_daily (symbol, day, high, low, price_sum, sample_count) "
     "FROM STDIN WITH (FORMAT csv)"),
    ("advice.csv",
     "COPY advice_records (id, created_at, kind, action, symbol, status, "
     "price_at_advice, price_t1, price_t7, price_t30) "
     "FROM STDIN WITH (FORMAT csv, NULL '')"),
    # CSV 格式下「未加引号的空字段」默认会被当成 NULL，会让 error_type 违反 NOT NULL。
    # 把 NULL 标记改成一个永远不会出现的串，空字段就会保持为空字符串。
    ("notify.csv",
     "COPY notification_send_logs (id, symbol, success, error_type, error_reason, "
     "created_at) FROM STDIN WITH (FORMAT csv, NULL '\\N')"),
    ("ai.csv",
     "COPY ai_call_logs (id, call_time, success, from_cache, total_tokens) "
     "FROM STDIN WITH (FORMAT csv)"),
]

INDEXES = """
CREATE INDEX idx_prices_symbol_ts ON prices(symbol, timestamp);
CREATE INDEX idx_prices_symbol_ts_price ON prices(symbol, timestamp, price);
CREATE INDEX idx_advice_symbol_id_desc ON advice_records(symbol, id DESC);
CREATE INDEX idx_notify_created ON notification_send_logs(created_at);
CREATE INDEX idx_notify_success ON notification_send_logs(success);
CREATE INDEX idx_ai_time ON ai_call_logs(call_time);
"""


def main():
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(DDL)

    for name, sql in LOADS:
        t0 = time.time()
        with open(f"{DATA}/{name}") as f:
            cur.copy_expert(sql, f)
        print(f"  {name:<20} {time.time() - t0:5.1f}s", flush=True)

    t0 = time.time()
    cur.execute(INDEXES)
    print(f"  建索引 {time.time() - t0:.1f}s", flush=True)

    t0 = time.time()
    cur.execute("ANALYZE")
    print(f"  ANALYZE {time.time() - t0:.1f}s", flush=True)

    # 关键：VACUUM 建立可见性映射，否则 index-only scan 不可用（实测退化 3 倍）
    t0 = time.time()
    cur.execute("VACUUM (ANALYZE)")
    print(f"  VACUUM  {time.time() - t0:.1f}s", flush=True)

    for table in ("prices", "prices_daily", "advice_records",
                  "notification_send_logs", "ai_call_logs"):
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"  {table:<24} {cur.fetchone()[0]:>9,} 行")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
