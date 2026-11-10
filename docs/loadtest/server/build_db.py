"""只从已有 CSV 构建 SQLite（schema 与索引与 App 完全一致）。

拆出来是因为 gen.py 第一步已经把 CSV 生成好了，重建库不需要重新造数。
"""

import csv
import os
import sqlite3
import time

OUT = "perfdata"
DB = f"{OUT}/perf.db"


def rows(name, convert):
    with open(f"{OUT}/{name}") as f:
        for row in csv.reader(f):
            yield convert(row)


def main():
    if os.path.exists(DB):
        os.remove(DB)
    conn = sqlite3.connect(DB)
    conn.isolation_level = None  # 手动控制事务，避免隐式事务嵌套
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.executescript("""
        CREATE TABLE prices (id INTEGER PRIMARY KEY, timestamp INTEGER NOT NULL,
                             symbol TEXT, price REAL);
        CREATE TABLE prices_daily (symbol TEXT NOT NULL, day INTEGER NOT NULL,
                                   high REAL NOT NULL, low REAL NOT NULL,
                                   price_sum REAL NOT NULL, sample_count INTEGER NOT NULL,
                                   PRIMARY KEY (symbol, day)) WITHOUT ROWID;
        CREATE TABLE advice_records (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL,
                                     kind TEXT NOT NULL, action TEXT NOT NULL,
                                     symbol TEXT NOT NULL, status TEXT NOT NULL,
                                     price_at_advice REAL, price_t1 REAL,
                                     price_t7 REAL, price_t30 REAL);
        CREATE TABLE notification_send_logs (id INTEGER PRIMARY KEY, symbol TEXT,
                                             success INTEGER NOT NULL,
                                             error_type TEXT NOT NULL DEFAULT '',
                                             error_reason TEXT NOT NULL DEFAULT '',
                                             created_at TEXT NOT NULL);
        CREATE TABLE ai_call_logs (id INTEGER PRIMARY KEY, call_time TEXT NOT NULL,
                                   success INTEGER NOT NULL,
                                   from_cache INTEGER NOT NULL DEFAULT 0,
                                   total_tokens INTEGER NOT NULL DEFAULT 0);
    """)

    jobs = [
        ("prices.csv",
         "INSERT INTO prices (id, timestamp, symbol, price) VALUES (?,?,?,?)",
         lambda r: (int(r[0]), int(r[1]), r[2], float(r[3]))),
        ("prices_daily.csv",
         "INSERT INTO prices_daily (symbol, day, high, low, price_sum, sample_count) "
         "VALUES (?,?,?,?,?,?)",
         lambda r: (r[0], int(r[1]), float(r[2]), float(r[3]), float(r[4]), int(r[5]))),
        ("advice.csv",
         "INSERT INTO advice_records (id, created_at, kind, action, symbol, status, "
         "price_at_advice, price_t1, price_t7, price_t30) VALUES (?,?,?,?,?,?,?,?,?,?)",
         lambda r: (int(r[0]), r[1], r[2], r[3], r[4], r[5], float(r[6]),
                    float(r[7]) if r[7] else None,
                    float(r[8]) if r[8] else None,
                    float(r[9]) if r[9] else None)),
        ("notify.csv",
         "INSERT INTO notification_send_logs (id, symbol, success, error_type, "
         "error_reason, created_at) VALUES (?,?,?,?,?,?)",
         lambda r: (int(r[0]), r[1], int(r[2]), r[3], r[4], r[5])),
        ("ai.csv",
         "INSERT INTO ai_call_logs (id, call_time, success, from_cache, total_tokens) "
         "VALUES (?,?,?,?,?)",
         lambda r: (int(r[0]), r[1], int(r[2]), int(r[3]), int(r[4]))),
    ]
    for name, sql, conv in jobs:
        t0 = time.time()
        conn.execute("BEGIN")
        conn.executemany(sql, rows(name, conv))
        conn.execute("COMMIT")
        print(f"  {name:<20} {time.time() - t0:5.1f}s", flush=True)

    t0 = time.time()
    conn.executescript("""
        CREATE INDEX idx_prices_symbol_ts ON prices(symbol, timestamp);
        CREATE INDEX idx_prices_symbol_ts_price ON prices(symbol, timestamp, price);
        CREATE INDEX idx_advice_symbol_id_desc ON advice_records(symbol, id DESC);
        CREATE INDEX idx_notify_created ON notification_send_logs(created_at);
        CREATE INDEX idx_notify_success ON notification_send_logs(success);
        CREATE INDEX idx_ai_time ON ai_call_logs(call_time);
    """)
    conn.execute("ANALYZE")
    print(f"  建索引 + ANALYZE {time.time() - t0:.1f}s", flush=True)

    for table in ("prices", "prices_daily", "advice_records",
                  "notification_send_logs", "ai_call_logs"):
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<24} {n:>9,} 行")
    conn.close()
    print(f"  perf.db = {os.path.getsize(DB) / 1024 / 1024:.0f} MB")


if __name__ == "__main__":
    main()
