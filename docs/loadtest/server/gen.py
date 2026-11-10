"""在服务器上生成与之前完全同构的数据集（只用标准库）。

产出：
  prices.csv         6,307,200 行 tick
  prices_daily.csv   732 行日线聚合（边生成边累加，不需要二次扫描）
  advice.csv         120,000 行
  notify.csv         300,000 行
  ai.csv             200,000 行
  perf.db            SQLite，schema 与索引和 App 里完全一致

用法：python3 gen.py [天数]
"""

import csv
import os
import random
import sqlite3
import sys
import time

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 365
INTERVAL = 10
SYMBOLS = [("gds_AUTD", 600.0, 0.03, 560.0, 660.0),
           ("hf_XAU", 2600.0, 0.18, 2300.0, 2950.0)]
RNG = random.Random(20261109)

OUT = "perfdata"


def gen_prices():
    os.makedirs(OUT, exist_ok=True)
    end = int(time.time())
    start = end - DAYS * 86400
    ticks = (end - start) // INTERVAL

    daily = {}
    t0 = time.time()
    with open(f"{OUT}/prices.csv", "w", newline="") as f:
        w = csv.writer(f)
        rid = 0
        for symbol, base, vol, lo, hi in SYMBOLS:
            price = base
            ts = start
            for _ in range(ticks):
                price += RNG.gauss(0, vol)
                if price < lo:
                    price = lo + abs(RNG.gauss(0, vol))
                elif price > hi:
                    price = hi - abs(RNG.gauss(0, vol))
                rid += 1
                p = round(price, 2)
                w.writerow((rid, ts, symbol, p))
                key = (symbol, (ts // 86400) * 86400)
                cur = daily.get(key)
                if cur is None:
                    daily[key] = [p, p, p, 1]
                else:
                    if p > cur[0]:
                        cur[0] = p
                    if p < cur[1]:
                        cur[1] = p
                    cur[2] += p
                    cur[3] += 1
                ts += INTERVAL
            print(f"  {symbol}: {ticks:,} 行  {time.time() - t0:.1f}s", flush=True)

    with open(f"{OUT}/prices_daily.csv", "w", newline="") as f:
        w = csv.writer(f)
        for (symbol, day), (high, low, total, cnt) in sorted(daily.items()):
            w.writerow((symbol, day, round(high, 2), round(low, 2), round(total, 6), cnt))
    print(f"  日线 {len(daily)} 行", flush=True)
    return ticks


def gen_advice():
    end = time.time()
    kinds = ["pre_purchase", "post_purchase", "plan_execution", "review"]
    actions = ["BUY_NOW", "BUY_PARTIAL", "WAIT", "AVOID", "HOLD", "ADD",
               "TAKE_PROFIT", "STOP_LOSS"]
    statuses = ["delivered"] * 6 + ["suppressed"] * 3 + ["acted", "acknowledged"]
    with open(f"{OUT}/advice.csv", "w", newline="") as f:
        w = csv.writer(f)
        for i in range(120_000):
            created = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(end - (120_000 - i) * 300)
            )
            age_days = ((end - (end - (120_000 - i) * 300)) // 86400)
            action = actions[i % len(actions)]
            w.writerow((
                i + 1, created, kinds[i % len(kinds)] if i % 7 else "review",
                action, "gds_AUTD", statuses[i % len(statuses)],
                round(RNG.uniform(560, 660), 2),
                round(RNG.uniform(560, 660), 2) if age_days > 1 else "",
                round(RNG.uniform(560, 660), 2) if age_days > 7 else "",
                round(RNG.uniform(560, 660), 2) if age_days > 30 else "",
            ))
    print("  建议 120,000 行", flush=True)


def gen_notify():
    end = time.time()
    channels = ["email", "wechat_work", "webhook"]
    errors = ["timeout", "auth_failed", "rate_limited", ""]
    with open(f"{OUT}/notify.csv", "w", newline="") as f:
        w = csv.writer(f)
        for i in range(300_000):
            created = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(end - RNG.randint(0, 365 * 86400))
            )
            err = errors[i % 4]
            # 6 列：id, symbol, success, error_type, error_reason, created_at
            w.writerow((i + 1, RNG.choice(["gds_AUTD", "hf_XAU"]),
                        0 if err else 1, err,
                        f"错误样例 {i % 97}: 发送超时" if err else "",
                        created))
    print("  通知 300,000 行", flush=True)


def gen_ai():
    end = time.time()
    with open(f"{OUT}/ai.csv", "w", newline="") as f:
        w = csv.writer(f)
        for i in range(200_000):
            call_time = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(end - RNG.randint(0, 365 * 86400))
            )
            success = 0 if i % 17 == 0 else 1
            pt, ct = RNG.randint(400, 2500), RNG.randint(100, 900)
            w.writerow((i + 1, call_time, success, 1 if i % 6 == 0 else 0, pt + ct))
    print("  AI 日志 200,000 行", flush=True)


def build_sqlite():
    """schema 与 App 完全一致（含覆盖索引）"""
    db = f"{OUT}/perf.db"
    if os.path.exists(db):
        os.remove(db)
    conn = sqlite3.connect(db)
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
    t0 = time.time()
    conn.execute("BEGIN")
    with open(f"{OUT}/prices.csv") as f:
        conn.executemany(
            "INSERT INTO prices (id, timestamp, symbol, price) VALUES (?,?,?,?)",
            ((int(a), int(b), c, float(d)) for a, b, c, d in csv.reader(f)),
        )
    conn.commit()
    print(f"  prices 导入 {time.time() - t0:.1f}s", flush=True)

    conn.execute("BEGIN")
    with open(f"{OUT}/prices_daily.csv") as f:
        conn.executemany(
            "INSERT INTO prices_daily (symbol, day, high, low, price_sum, sample_count) "
            "VALUES (?,?,?,?,?,?)",
            ((a, int(b), float(c), float(d), float(e), int(g))
             for a, b, c, d, e, g in csv.reader(f)),
        )
    conn.commit()

    def rows(name, convert):
        with open(f"{OUT}/{name}") as f:
            for row in csv.reader(f):
                yield convert(row)

    conn.execute("BEGIN")
    conn.executemany(
        "INSERT INTO advice_records (id, created_at, kind, action, symbol, status, "
        "price_at_advice, price_t1, price_t7, price_t30) VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows("advice.csv", lambda r: (
            int(r[0]), r[1], r[2], r[3], r[4], r[5], float(r[6]),
            float(r[7]) if r[7] else None,
            float(r[8]) if r[8] else None,
            float(r[9]) if r[9] else None)),
    )
    conn.execute("BEGIN")
    conn.executemany(
        "INSERT INTO notification_send_logs (id, symbol, success, error_type, "
        "error_reason, created_at) VALUES (?,?,?,?,?,?)",
        rows("notify.csv", lambda r: (int(r[0]), r[1], int(r[2]), r[3], r[4], r[5])),
    )
    conn.execute("BEGIN")
    conn.executemany(
        "INSERT INTO ai_call_logs (id, call_time, success, from_cache, total_tokens) "
        "VALUES (?,?,?,?,?)",
        rows("ai.csv", lambda r: (int(r[0]), r[1], int(r[2]), int(r[3]), int(r[4]))),
    )
    conn.commit()

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
    conn.commit()
    conn.close()
    print(f"  建索引 + ANALYZE {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    t0 = time.time()
    print(f"生成 {DAYS} 天 × {INTERVAL}s 数据 …", flush=True)
    gen_prices()
    gen_advice()
    gen_notify()
    gen_ai()
    print("构建 SQLite …", flush=True)
    build_sqlite()
    size = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT))
    print(f"完成，{OUT}/ 共 {size / 1024 / 1024:.0f} MB，耗时 {time.time() - t0:.1f}s")
