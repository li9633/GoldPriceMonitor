"""定向实验（第二轮）：
2b. last_pushed() 的索引形状对比
4. 连接级页缓存 / 复用连接的真实差异
5. 并发读的扩展上限
"""

import os
import sqlite3
import statistics
import sys
import threading
import time
from contextlib import contextmanager

sys.path.insert(0, r"C:\Programer\GoldPriceMonitor\backend")


def pct(samples, p):
    ordered = sorted(samples)
    return ordered[min(int(len(ordered) * p / 100), len(ordered) - 1)]


def bench(label, fn, repeat=10, warmup=2):
    for _ in range(warmup):
        fn()
    lat = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        lat.append((time.perf_counter() - t0) * 1000)
    print(f"{label:<46} p50={statistics.median(lat):8.1f}  p95={pct(lat, 95):8.1f} ms")
    return statistics.median(lat)


def section(t):
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


DB = "data/portfolio.db"
SQL = ("SELECT * FROM advice_records WHERE symbol = ? AND status != ? "
       "ORDER BY id DESC LIMIT 1")
PARAMS = ("gds_AUTD", "suppressed")


def plan_of(sql=SQL, params=PARAMS):
    conn = sqlite3.connect(DB)
    rows = conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    conn.close()
    return " | ".join(r[3] for r in rows)


def exp_index_shapes():
    section("实验 2b：last_pushed() 索引形状对比（12 万行，symbol 全部相同）")
    from mapper.advice_mapper import AdviceMapper

    mapper = AdviceMapper()

    conn = sqlite3.connect(DB)
    for name in ("idx_a_symbol_id", "idx_b_partial", "idx_c_status_id"):
        conn.execute(f"DROP INDEX IF EXISTS {name}")
    conn.commit()
    conn.close()

    print(f"  基线执行计划：{plan_of()}")
    bench("① 现状（只有 idx_advice_symbol）", lambda: mapper.last_pushed("gds_AUTD"), 15)

    conn = sqlite3.connect(DB)
    t0 = time.perf_counter()
    conn.execute("CREATE INDEX idx_a_symbol_id ON advice_records(symbol, id DESC)")
    conn.commit()
    conn.close()
    print(f"\n  + idx_a_symbol_id(symbol, id DESC)  建索引 {(time.perf_counter() - t0) * 1000:.0f} ms")
    print(f"  执行计划：{plan_of()}")
    bench("② 加 (symbol, id DESC)", lambda: mapper.last_pushed("gds_AUTD"), 15)

    conn = sqlite3.connect(DB)
    conn.execute("DROP INDEX idx_a_symbol_id")
    t0 = time.perf_counter()
    conn.execute(
        "CREATE INDEX idx_b_partial ON advice_records(symbol, id DESC) "
        "WHERE status != 'suppressed'"
    )
    conn.commit()
    conn.close()
    print(f"\n  + idx_b_partial(symbol, id DESC) WHERE status != 'suppressed'  "
          f"建索引 {(time.perf_counter() - t0) * 1000:.0f} ms")
    print(f"  执行计划：{plan_of()}")
    bench("③ 加部分索引", lambda: mapper.last_pushed("gds_AUTD"), 15)


class CacheProbe:
    """在真实 PriceMapper 上只替换连接策略，其余逻辑不动"""

    def __init__(self, cache_kb: int, reuse: bool):
        from mapper.price_mapper import PriceMapper

        probe = self

        class M(PriceMapper):
            def __init__(self):
                super().__init__("data/prices.db")
                self._extra_pragmas = (f"PRAGMA cache_size = -{cache_kb}",)

            def _get_connection(self):
                if probe._reuse:
                    if probe._conn is None:
                        probe._conn = super()._get_connection()
                    return probe._conn
                return super()._get_connection()

            @contextmanager
            def _session(self):
                conn = self._get_connection()
                try:
                    yield conn
                    if not probe._reuse:
                        conn.commit()
                finally:
                    if not probe._reuse:
                        conn.close()

        self._reuse = reuse
        self._conn = None
        self.mapper = M()

    def snapshot(self):
        return self.mapper.get_check_snapshot("gds_AUTD")


def exp_page_cache():
    section("实验 4：连接策略 × 页缓存（get_check_snapshot on 669MB 库）")
    probes = {}
    for label, cache_kb, reuse in (
        ("每次新建连接 + 8MB 缓存（现状）", 8000, False),
        ("每次新建连接 + 64MB 缓存", 65536, False),
        ("复用连接 + 8MB 缓存", 8000, True),
        ("复用连接 + 64MB 缓存", 65536, True),
    ):
        p = CacheProbe(cache_kb, reuse)
        probes[label] = p
        bench(label, p.snapshot, 8, warmup=3)


def exp_avail():
    section("实验 5：并发读扩展性（1 核工作量，看线程数能否换吞吐）")
    from mapper.price_mapper import PriceMapper

    mapper = PriceMapper()
    for n in (1, 2, 4, 8, 16):
        lat = []
        lock = threading.Lock()

        def worker():
            local = []
            for _ in range(5):
                t0 = time.perf_counter()
                mapper.get_check_snapshot("gds_AUTD")
                local.append((time.perf_counter() - t0) * 1000)
            with lock:
                lat.extend(local)

        ts = [threading.Thread(target=worker) for _ in range(n)]
        t0 = time.perf_counter()
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        wall = time.perf_counter() - t0
        print(f"  并发 {n:<3} 总请求 {len(lat):<4} QPS={len(lat) / wall:7.1f}  "
              f"p50={statistics.median(lat):7.1f} ms  p95={pct(lat, 95):7.1f} ms")


def main():
    exp_index_shapes()
    exp_page_cache()
    exp_avail()


if __name__ == "__main__":
    main()
