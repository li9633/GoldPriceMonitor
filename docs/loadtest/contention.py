"""读写争用压测：在监控线程持续写入的同时，量读接口的延迟变化。

场景：
  A. 无写入（基线）
  B. 真实写入速率 0.2 行/秒（等于生产 10s 落两条）
  C. 高写入 20 行/秒 / 50 行/秒（探测 SQLite 写锁上限）
"""

import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = f"http://127.0.0.1:{sys.argv[1] if len(sys.argv) > 1 else 8765}"
PY = sys.executable
STOP = os.path.join("data", ".writer_stop")
PATH = "/api/prices/dashboard"


def get(path, timeout=120):
    req = urllib.request.Request(BASE + path, headers={"Accept": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
            code = resp.status
    except urllib.error.HTTPError as exc:
        exc.read()
        code = exc.code
    except Exception as exc:  # noqa: BLE001
        return (time.perf_counter() - t0) * 1000, 0, type(exc).__name__
    return (time.perf_counter() - t0) * 1000, code, ""


def pct(samples, p):
    ordered = sorted(samples)
    return ordered[min(int(len(ordered) * p / 100), len(ordered) - 1)]


def measure(seconds, label):
    lat = []
    errors = 0
    detail = ""
    stop = time.time() + seconds
    while time.time() < stop:
        ms, code, extra = get(PATH)
        lat.append(ms)
        if code != 200:
            errors += 1
            detail = detail or f"{code}:{extra}"
    print(f"{label:<30} n={len(lat):<3} p50={statistics.median(lat):7.1f}  "
          f"p95={pct(lat, 95):7.1f}  max={max(lat):7.1f} ms  "
          f"错误={errors} {detail}")
    return statistics.median(lat), pct(lat, 95), errors


def start_writer(rate):
    if os.path.exists(STOP):
        os.remove(STOP)
    proc = subprocess.Popen(
        [PY, "writer.py", str(rate)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    time.sleep(2.0)
    return proc


def stop_writer(proc):
    open(STOP, "w").close()
    try:
        out, _ = proc.communicate(timeout=30)
        for line in (out or "").strip().splitlines():
            if "结束" in line or "错误" in line:
                print(f"   {line}")
    except subprocess.TimeoutExpired:
        proc.kill()
    if os.path.exists(STOP):
        os.remove(STOP)


def main():
    print("=" * 80)
    print(f"读延迟 vs 并发写入（接口 {PATH}）")
    print("=" * 80)
    measure(6, "预热")
    measure(12, "A. 无写入（基线）")

    proc = start_writer(0.2)
    measure(12, "B. 写入 0.2/s（生产速率）")
    stop_writer(proc)

    for rate in (20, 50):
        proc = start_writer(rate)
        measure(12, f"C. 写入 {rate}/s")
        stop_writer(proc)


if __name__ == "__main__":
    main()
