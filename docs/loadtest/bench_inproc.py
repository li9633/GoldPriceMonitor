"""进程内压测：直接跑真实 service / mapper，网络与 LLM 打桩，只看 DB 与 CPU 开销。

以 goldperf 为 cwd 运行，数据落在 ./data，与项目真实库隔离。
"""

import os
import statistics
import sys
import threading
import time
import traceback

BACKEND = r"C:\Programer\GoldPriceMonitor\backend"
sys.path.insert(0, BACKEND)

from utils.time_utils import now  # noqa: E402

RESULTS = []


def pct(samples, p):
    if not samples:
        return 0.0
    ordered = sorted(samples)
    idx = min(int(len(ordered) * p / 100), len(ordered) - 1)
    return ordered[idx]


def bench(label, fn, repeat=1, warmup=1, note=""):
    for _ in range(warmup):
        try:
            fn()
        except Exception:
            traceback.print_exc()
            return None
    samples = []
    errors = 0
    for _ in range(repeat):
        t0 = time.perf_counter()
        try:
            fn()
        except Exception as exc:
            errors += 1
            if errors == 1:
                print(f"  !! {label} 出错：{type(exc).__name__}: {exc}")
        samples.append((time.perf_counter() - t0) * 1000)
    if not samples:
        return None
    row = {
        "label": label,
        "n": repeat,
        "p50": statistics.median(samples),
        "p95": pct(samples, 95),
        "max": max(samples),
        "errors": errors,
        "note": note,
    }
    RESULTS.append(row)
    print(f"{label:<46} p50={row['p50']:8.1f}  p95={row['p95']:8.1f}  "
          f"max={row['max']:8.1f} ms{'' if not errors else f'  错误={errors}'}")
    return row


class StubPriceService:
    """打桩：不发网络请求，返回固定行情（真实抓价是 100-500ms 级网络耗时）"""

    def __init__(self):
        self._symbol_name_map = {"gds_AUTD": "黄金T+D", "hf_XAU": "伦敦金"}

    @property
    def symbol_name_map(self):
        return self._symbol_name_map

    def refresh_symbol_name_map(self):
        return None

    def fetch_current_price(self, symbol):
        return {
            "symbol": symbol,
            "price": 601.23 if symbol == "gds_AUTD" else 2643.5,
            "time": "12:00:00",
            "date": now().strftime("%Y-%m-%d"),
            "name": self._symbol_name_map.get(symbol, symbol),
            "converted_cny_price": 608.4 if symbol == "hf_XAU" else None,
        }

    def fetch_all_gold_prices(self, symbols):
        return {s: self.fetch_current_price(s) for s in symbols}


def section(title):
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main():
    section("0. 环境")
    from config import (MODEL_POOL_DB_FILE, PORTFOLIO_DB_FILE,
                        PRICE_HISTORY_DB_FILE, SYSTEM_SETTINGS_DB_FILE)
    import sqlite3

    for label, path in (
        ("prices", PRICE_HISTORY_DB_FILE),
        ("portfolio", PORTFOLIO_DB_FILE),
        ("settings", SYSTEM_SETTINGS_DB_FILE),
        ("model_pool", MODEL_POOL_DB_FILE),
    ):
        size = os.path.getsize(path) / 1024 / 1024
        print(f"  {label:<12} {path:<26} {size:>7.1f} MB")

    conn = sqlite3.connect(PRICE_HISTORY_DB_FILE)
    n_prices = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    n_sym = conn.execute("SELECT COUNT(DISTINCT symbol) FROM prices").fetchone()[0]
    span = conn.execute("SELECT MIN(timestamp), MAX(timestamp) FROM prices").fetchone()
    conn.close()
    print(f"  prices 行数={n_prices:,} 品种={n_sym} 跨度={(span[1] - span[0]) / 86400:.0f} 天")

    from mapper.advice_mapper import AdviceMapper
    from mapper.ai_stats_mapper import AiStatsMapper
    from mapper.notification_stats_mapper import NotificationStatsMapper
    from mapper.price_mapper import PriceMapper
    from service.advice.advice_engine import AdviceEngine
    from service.advice.entry_strategy import EntryStrategyEvaluator
    from service.monitor_service import MonitorService
    from service.notification_stats_service import NotificationStatsService
    from service.price_history_service import PriceHistoryService

    price_mapper = PriceMapper()
    advice_mapper = AdviceMapper()
    ai_mapper = AiStatsMapper()
    notify_mapper = NotificationStatsMapper()

    section("1. 价格热路径（每个建议评估 / 每次手动建议都会走）")
    bench("get_check_snapshot(gds_AUTD)", lambda: price_mapper.get_check_snapshot("gds_AUTD"), 20)
    bench("get_check_snapshot(hf_XAU)", lambda: price_mapper.get_check_snapshot("hf_XAU"), 20)
    bench("get_latest_price()", lambda: price_mapper.get_latest_price("gds_AUTD"), 50)
    bench("get_record_count()  COUNT(*)", lambda: price_mapper.get_record_count("gds_AUTD"), 10)
    bench("get_price_near(90 天前)", lambda: price_mapper.get_price_near(
        "gds_AUTD", int(now().timestamp()) - 90 * 86400), 20)

    section("2. 图表与看板（前端首页 10s 轮询 / 打开图表）")
    bench("get_dashboard_data(hours=24)", lambda: price_mapper.get_dashboard_data(hours=24), 10)
    bench("get_chart_series(24h)", lambda: price_mapper.get_chart_series("gds_AUTD", hours=24), 10)
    bench("get_chart_series(7d)", lambda: price_mapper.get_chart_series("gds_AUTD", hours=168), 5)
    bench("get_chart_series(30d)", lambda: price_mapper.get_chart_series("gds_AUTD", hours=720), 5)
    bench("get_chart_series(1 年)", lambda: price_mapper.get_chart_series("gds_AUTD", hours=8760), 5)
    bench("get_price_series(24h)", lambda: price_mapper.get_price_series("gds_AUTD", 24), 10)
    bench("get_price_statistics(24h)", lambda: price_mapper.get_price_statistics("gds_AUTD", hours=24), 10)
    bench("get_price_trend(24h)", lambda: price_mapper.get_price_trend("gds_AUTD", hours=24), 10)

    section("3. 建议引擎（规则 + 持仓 + 建仓回测）")
    engine = AdviceEngine()
    engine.price_service = StubPriceService()
    engine.advisor.phrase = lambda ctx, draft: ("（桩）建议文案", "stub-model")
    bench("build_context() 完整上下文", lambda: engine.build_context("gds_AUTD", 601.23), 10)
    bench("compute() 端到端（LLM 已打桩）",
          lambda: engine.compute("gds_AUTD", 601.23, 608.4, 2643.5), 10)
    evaluator = EntryStrategyEvaluator()
    bench("entry_strategy.fetch_series()  缓存命中", lambda: evaluator.fetch_series("gds_AUTD", 365), 20)
    evaluator.invalidate_cache()
    bench("entry_strategy.fetch_series()  冷启动（1 年聚合）",
          lambda: evaluator.fetch_series("gds_AUTD", 365), 3)
    evaluator.invalidate_cache()
    bench("entry_strategy.evaluate()  冷启动", lambda: evaluator.evaluate("gds_AUTD", 601.23, lookback_days=365), 3)

    section("4. 建议历史（前端分页）")
    bench("history limit=50 offset=0", lambda: advice_mapper.list_advice(None, None, None, 50, 0), 20)
    bench("history limit=50 offset=2000", lambda: advice_mapper.list_advice(None, None, None, 50, 2000), 10)
    bench("history limit=50 offset=50000", lambda: advice_mapper.list_advice(None, None, None, 50, 50000), 5)
    bench("history limit=50 offset=100000", lambda: advice_mapper.list_advice(None, None, None, 50, 100000), 3)
    bench("count_advice()", lambda: advice_mapper.count_advice(None, None, None), 10)
    bench("last_pushed()  推送节流用", lambda: advice_mapper.last_pushed("gds_AUTD"), 20)
    bench("list_pending_reviews(T+1)", lambda: advice_mapper.list_pending_reviews(1), 10)
    bench("review_stats()", lambda: advice_mapper.review_stats(), 10)

    section("5. 统计页（30s 轮询触发几十条聚合）")
    bench("ai_stats.get_overview()", lambda: ai_mapper.get_overview(), 5, note="内部多条聚合")
    bench("ai_stats.get_trend()", lambda: ai_mapper.get_trend(), 5)
    bench("ai_stats.get_logs(page=1)", lambda: ai_mapper.get_logs(1, 20), 10)
    bench("notify_stats.get_overview()", lambda: notify_mapper.get_overview(), 5)
    bench("notify_stats.daily_trend()", lambda: notify_mapper.get_daily_trend(), 5)
    bench("notify_stats.by_channel()", lambda: notify_mapper.by_channel(), 5)

    section("6. 完整 tick（真实 MonitorService，抓价/LLM 打桩）")
    monitor = MonitorService()
    monitor.price_service = StubPriceService()
    monitor.advice_engine.price_service = StubPriceService()
    monitor.advice_engine.advisor.phrase = lambda ctx, draft: ("（桩）文案", "stub")
    # 关掉时间闸门，确保整条链路（含建议评估）都跑到
    import service.monitor_service as ms
    monitor.send_gate.policy_decision = lambda: type(
        "D", (), {"allowed": True, "reason": "", "detail": "", "policy": None}
    )()
    monitor.check_interval = 0
    bench("_tick() 单轮（含两次落库 + 5 触发器）", monitor._tick, 30, warmup=3)
    bench("_save_prices() 两次独立事务", lambda: monitor._save_prices(
        {"gds_AUTD": {"price": 601.0}, "hf_XAU": {"price": 2640.0}}, 601.0), 30)

    section("7. 并发压测（线程争用 / SQLITE_BUSY）")

    def concurrent_reader(n_threads, n_iter, label):
        errors = []
        lat = []

        def worker():
            for _ in range(n_iter):
                t0 = time.perf_counter()
                try:
                    price_mapper.get_check_snapshot("gds_AUTD")
                except Exception as exc:
                    errors.append(f"{type(exc).__name__}: {exc}")
                lat.append((time.perf_counter() - t0) * 1000)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        t0 = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        wall = time.perf_counter() - t0
        qps = len(lat) / wall
        print(f"{label:<46} 并发={n_threads:<3} 总请求={len(lat):<5} "
              f"QPS={qps:7.1f}  p50={statistics.median(lat):7.1f} "
              f"p95={pct(lat, 95):7.1f} ms  错误={len(errors)}")
        if errors:
            print(f"    首个错误：{errors[0]}")
        RESULTS.append({"label": label, "n": len(lat), "p50": statistics.median(lat),
                        "p95": pct(lat, 95), "max": max(lat), "errors": len(errors),
                        "note": f"并发 {n_threads} / QPS {qps:.0f}"})
        return qps

    for n in (1, 4, 8, 16, 32):
        concurrent_reader(n, 10, "纯读：get_check_snapshot")

    def mixed_workload(n_threads, n_iter):
        """读 + 写混合：模拟监控线程写入与前端读并发"""
        errors = []
        lat = []

        def reader():
            for _ in range(n_iter):
                t0 = time.perf_counter()
                try:
                    price_mapper.get_check_snapshot("gds_AUTD")
                except Exception as exc:
                    errors.append(f"reader {type(exc).__name__}: {exc}")
                lat.append((time.perf_counter() - t0) * 1000)

        def writer():
            for _ in range(n_iter * 2):
                t0 = time.perf_counter()
                try:
                    price_mapper.save_price("gds_AUTD", 601.5)
                except Exception as exc:
                    errors.append(f"writer {type(exc).__name__}: {exc}")
                lat.append((time.perf_counter() - t0) * 1000)

        threads = [threading.Thread(target=reader) for _ in range(n_threads)]
        threads += [threading.Thread(target=writer) for _ in range(2)]
        t0 = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        wall = time.perf_counter() - t0
        print(f"{'混合读写（%d 读 + 2 写）' % n_threads:<46} 总请求={len(lat):<5} "
              f"QPS={len(lat) / wall:7.1f}  p50={statistics.median(lat):7.1f} "
              f"p95={pct(lat, 95):7.1f} ms  错误={len(errors)}")
        if errors:
            print(f"    首个错误：{errors[0]}")
        RESULTS.append({"label": f"混合读写 x{n_threads}+2w", "n": len(lat),
                        "p50": statistics.median(lat), "p95": pct(lat, 95),
                        "max": max(lat), "errors": len(errors), "note": ""})

    mixed_workload(8, 10)
    mixed_workload(16, 10)

    section("汇总：Top 10 最慢")
    for row in sorted(RESULTS, key=lambda r: -r["p50"])[:10]:
        print(f"  {row['label']:<44} p50={row['p50']:8.1f} ms  p95={row['p95']:8.1f} ms")


if __name__ == "__main__":
    main()
