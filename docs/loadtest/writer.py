"""模拟监控线程的写负载（独立进程，与 HTTP 服务共享同一 SQLite 文件）。

用法：
  python writer.py            # 1 行/秒，模拟真实 tick（10s 写 2 行）
  python writer.py 50         # 50 行/秒，压测写入上限
"""

import os
import sys
import time

BACKEND = r"C:\Programer\GoldPriceMonitor\backend"
sys.path.insert(0, BACKEND)

from mapper.price_mapper import PriceMapper  # noqa: E402

RATE = float(sys.argv[1]) if len(sys.argv) > 1 else 0.2
DURATION = float(sys.argv[2]) if len(sys.argv) > 2 else 0
STOP_FLAG = os.path.join("data", ".writer_stop")


def main():
    mapper = PriceMapper()
    interval = 1.0 / RATE if RATE > 0 else 1.0
    written = 0
    errors = 0
    t0 = time.perf_counter()
    print(f"[writer] 写入 {RATE}/s，间隔 {interval * 1000:.0f}ms", flush=True)
    while True:
        if os.path.exists(STOP_FLAG):
            break
        if DURATION and time.perf_counter() - t0 > DURATION:
            break
        try:
            mapper.save_price("gds_AUTD", 601.0)
            written += 1
        except Exception as exc:  # noqa: BLE001
            errors += 1
            if errors <= 3:
                print(f"[writer] 错误：{type(exc).__name__}: {exc}", flush=True)
        time.sleep(interval)
    elapsed = time.perf_counter() - t0
    print(f"[writer] 结束 written={written} errors={errors} "
          f"实耗 {elapsed:.1f}s 速率 {written / elapsed:.1f}/s", flush=True)


if __name__ == "__main__":
    main()
