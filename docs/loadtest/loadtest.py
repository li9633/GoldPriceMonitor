"""HTTP 压测：对真实 uvicorn 服务做并发梯度 + 混合场景。

用法：
  python loadtest.py [端口]
"""

import json
import random
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request

BASE = f"http://127.0.0.1:{sys.argv[1] if len(sys.argv) > 1 else 8765}"

# 只压「前端会真正调」的读接口；写接口单独测
SAFE_GETS = [
    "/api/prices/dashboard",
    "/api/prices/count",
    "/api/prices/statistics?hours=24",
    "/api/prices/trend?hours=24",
    "/api/prices/chart?hours=24",
    "/api/prices/recent?hours=24",
    "/api/advice/history?limit=50",
    "/api/advice/reviews/stats",
    "/api/advice/followups/pending",
    "/api/ai-stats/overview",
    "/api/ai-stats/trend",
    "/api/ai-stats/logs?page=1&page_size=20",
    "/api/notification-stats/overview",
    "/api/notification-stats/daily-trend",
    "/api/notification-stats/by-channel",
    "/api/notification-stats/top-failures",
    "/api/notification-stats/logs?page=1&page_size=20",
    "/api/portfolio/lots",
    "/api/portfolio/summary",
    "/api/portfolio/plans",
    "/api/exchange-rate/count",
    "/api/exchange-rate/dashboard",
    "/api/exchange-rate/chart",
    "/api/providers",
    "/api/pricing",
    "/api/runtime-status",
]

# 前端各页面真实轮询权重（首页 dashboard 10s 一次最重）
PAGE_MIX = {
    "/api/prices/dashboard": 30,
    "/api/prices/chart?hours=24": 10,
    "/api/prices/statistics?hours=24": 8,
    "/api/prices/trend?hours=24": 8,
    "/api/ai-stats/overview": 8,
    "/api/ai-stats/trend": 5,
    "/api/notification-stats/overview": 5,
    "/api/notification-stats/daily-trend": 4,
    "/api/portfolio/summary": 6,
    "/api/advice/history?limit=50": 6,
    "/api/runtime-status": 6,
    "/api/exchange-rate/dashboard": 4,
}


def pct(samples, p):
    if not samples:
        return 0.0
    ordered = sorted(samples)
    return ordered[min(int(len(ordered) * p / 100), len(ordered) - 1)]


def get(path, timeout=60):
    req = urllib.request.Request(BASE + path, headers={"Accept": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            code = resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read()
        code = exc.code
    except Exception as exc:  # noqa: BLE001
        return (time.perf_counter() - t0) * 1000, 0, f"{type(exc).__name__}"
    return (time.perf_counter() - t0) * 1000, code, len(body)


def wait_server(retries=60):
    for _ in range(retries):
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=1):
                return True
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return False


def section(title):
    print(f"\n{'=' * 80}\n{title}\n{'=' * 80}", flush=True)


def single_endpoint(path, n=10):
    lat = []
    codes = []
    for _ in range(n):
        ms, code, _ = get(path)
        lat.append(ms)
        codes.append(code)
    bad = sum(1 for c in codes if c != 200)
    print(f"{path:<44} p50={statistics.median(lat):7.1f}  p95={pct(lat, 95):7.1f} "
          f"max={max(lat):7.1f} ms  非200={bad}")


def ramp(path, thread_counts, n_iter=8):
    print(f"\n--- 并发梯度：{path} ---")
    rows = []
    for n in thread_counts:
        lat = []
        errors = []
        lock = threading.Lock()

        def worker():
            local = []
            for _ in range(n_iter):
                ms, code, extra = get(path)
                local.append(ms)
                if code != 200:
                    with lock:
                        errors.append(f"{code}:{extra}")
            with lock:
                lat.extend(local)

        threads = [threading.Thread(target=worker) for _ in range(n)]
        t0 = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        wall = time.perf_counter() - t0
        qps = len(lat) / wall
        err = len(errors)
        print(f"  并发 {n:<3} 请求 {len(lat):<5} QPS {qps:7.1f}  "
              f"p50 {statistics.median(lat):7.1f}  p95 {pct(lat, 95):7.1f}  "
              f"p99 {pct(lat, 99):7.1f} ms  错误 {err}")
        if err:
            print(f"     首个错误：{errors[0]}")
        rows.append((n, qps, statistics.median(lat), pct(lat, 95), err))
    return rows


def mixed_run(seconds=30, users=8, label=""):
    """按前端页面权重随机打请求，模拟真实多用户"""
    paths, weights = zip(*PAGE_MIX.items())
    lat = []
    errors = []
    per_path = {}
    lock = threading.Lock()
    stop = time.time() + seconds

    def worker():
        local = []
        local_err = []
        local_path = {}
        rnd = random.Random()
        while time.time() < stop:
            path = rnd.choices(paths, weights)[0]
            ms, code, extra = get(path)
            local.append(ms)
            local_path.setdefault(path, []).append(ms)
            if code != 200:
                local_err.append(f"{path} -> {code}:{extra}")
        with lock:
            lat.extend(local)
            errors.extend(local_err)
            for k, v in local_path.items():
                per_path.setdefault(k, []).extend(v)

    threads = [threading.Thread(target=worker) for _ in range(users)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - t0
    print(f"{label:<28} 用户 {users:<3} 请求 {len(lat):<6} QPS {len(lat) / wall:7.1f}  "
          f"p50 {statistics.median(lat):7.1f}  p95 {pct(lat, 95):7.1f}  "
          f"p99 {pct(lat, 99):7.1f} ms  错误 {len(errors)}")
    if errors:
        print(f"    首个错误：{errors[0]}")
    print("    各接口 p50：")
    for path, samples in sorted(per_path.items(), key=lambda kv: -statistics.median(kv[1]))[:8]:
        print(f"      {path:<44} p50={statistics.median(samples):7.1f} "
              f"p95={pct(samples, 95):7.1f} ms  n={len(samples)}")
    return per_path


def probe_loop(path, seconds, label):
    """单线程持续打一个接口，用于对比「有无写入并发」的差异"""
    lat = []
    errors = []
    stop = time.time() + seconds
    while time.time() < stop:
        ms, code, extra = get(path)
        lat.append(ms)
        if code != 200:
            errors.append(f"{code}:{extra}")
    print(f"{label:<34} 请求 {len(lat):<4} p50 {statistics.median(lat):7.1f}  "
          f"p95 {pct(lat, 95):7.1f}  max {max(lat):7.1f} ms  错误 {len(errors)}")
    return lat


def main():
    if not wait_server():
        print("服务未启动")
        return

    section("0. 单接口基线（顺序请求）")
    for path in SAFE_GETS:
        single_endpoint(path, n=5)

    section("1. 并发梯度：/api/prices/dashboard（首页 10s 轮询）")
    ramp("/api/prices/dashboard", (1, 2, 4, 8, 16, 32), 6)

    section("2. 并发梯度：/api/ai-stats/overview（30s 轮询，内部几十条聚合）")
    ramp("/api/ai-stats/overview", (1, 2, 4, 8, 16), 5)

    section("3. 混合场景（按前端真实调用比例）")
    mixed_run(seconds=20, users=1, label="1 用户（真实单机）")
    mixed_run(seconds=20, users=8, label="8 用户")
    mixed_run(seconds=20, users=24, label="24 用户")


if __name__ == "__main__":
    main()
