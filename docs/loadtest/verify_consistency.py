"""大规模一致性验证：630 万行真实数据上核对日线聚合与原始表。

单元测试只覆盖了几百行的小样本，这里验证「大规模 + 真实分布」下：
  1. SUM(sample_count) == COUNT(*)
  2. SUM(price_sum)   == SUM(price)
  3. MIN(low)         == MIN(price)（全区间 / 90 天 / 180 天）
  4. 1 年图表与旧实现（原始表 GROUP BY 日桶）逐点一致
  5. 首页总记录数 == COUNT(*)
  6. 二次启动不重复重建（自愈逻辑不误伤）
"""

import sqlite3
import statistics
import sys
import time

sys.path.insert(0, r"C:\Programer\GoldPriceMonitor\backend")

from mapper.price_mapper import PriceMapper, _day_bucket  # noqa: E402
from utils.time_utils import now  # noqa: E402

DB = "data/prices.db"
SYMBOL = "gds_AUTD"
ok = True


def check(label, cond, detail=""):
    global ok
    if not cond:
        ok = False
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}{('  ' + detail) if detail else ''}")


def main():
    conn = sqlite3.connect(DB)
    raw_total = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    daily_total, daily_sum, daily_min = conn.execute(
        "SELECT SUM(sample_count), SUM(price_sum), MIN(low) FROM prices_daily"
    ).fetchone()
    raw_sum, raw_min = conn.execute("SELECT SUM(price), MIN(price) FROM prices").fetchone()
    conn.close()

    print("=" * 74)
    print(f"库：{raw_total:,} 行 tick")
    print("=" * 74)

    check("① 计数一致 SUM(sample_count) == COUNT(*)",
          daily_total == raw_total, f"{daily_total:,} vs {raw_total:,}")
    check("② 价格和一致 SUM(price_sum) == SUM(price)",
          abs(daily_sum - raw_sum) < 1e-3, f"差值 {abs(daily_sum - raw_sum):.9f}")
    check("③ 全区间最低价一致 MIN(low) == MIN(price)",
          abs(daily_min - raw_min) < 1e-9, f"{daily_min} vs {raw_min}")

    m = PriceMapper()
    now_ts = int(now().timestamp())
    conn = sqlite3.connect(DB)
    for days in (90, 180):
        cutoff = now_ts - days * 86400
        raw = conn.execute(
            "SELECT MIN(price) FROM prices WHERE symbol = ? AND timestamp > ?",
            (SYMBOL, cutoff),
        ).fetchone()[0]
        daily = conn.execute(
            "SELECT MIN(low) FROM prices_daily WHERE symbol = ? AND day >= ?",
            (SYMBOL, _day_bucket(cutoff)),
        ).fetchone()[0]
        check(f"④ MIN 近 {days} 天（日线 vs 原始）", abs(raw - daily) < 1e-9,
              f"raw={raw} daily={daily}")

    # 新旧图表实现对比：日线表 vs 原始表按日桶 GROUP BY
    hours = 8760
    lo = now_ts - hours * 3600
    t0 = time.perf_counter()
    new_series = m.get_chart_series(SYMBOL, hours=hours)
    new_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    old_rows = conn.execute(
        "SELECT (timestamp / 86400) * 86400 AS bucket, AVG(price) AS price "
        "FROM prices WHERE symbol = ? AND timestamp > ? "
        "GROUP BY bucket ORDER BY bucket",
        (SYMBOL, lo),
    ).fetchall()
    old_ms = (time.perf_counter() - t0) * 1000
    old_series = [(b, round(p, 2)) for b, p in old_rows]

    new_map = {int(ts.timestamp()): avg for ts, avg in new_series}
    old_map = dict(old_series)
    common = sorted(set(new_map) & set(old_map))
    first_bucket = min(old_map) if old_map else None
    inner = [b for b in common if b != first_bucket]
    diffs = [abs(new_map[b] - old_map[b]) for b in inner]
    boundary_diff = (
        abs(new_map[first_bucket] - old_map[first_bucket])
        if first_bucket in new_map and first_bucket in old_map
        else 0.0
    )
    missing = sorted(set(old_map) - set(new_map))
    extra = sorted(set(new_map) - set(old_map))

    print(f"\n  图表：新实现 {len(new_series)} 点 / {new_ms:.1f}ms，"
          f"旧实现 {len(old_series)} 点 / {old_ms:.1f}ms")
    check("⑤ 图表点数一致", len(new_series) == len(old_series),
          f"{len(new_series)} vs {len(old_series)}")
    check("⑥ 桶集合完全一致", not missing and not extra,
          f"缺 {len(missing)} 个、多 {len(extra)} 个")
    check("⑦ 除首桶外每个桶均价完全一致",
          max(diffs) <= 0.01 if diffs else True,
          f"{len(inner)} 个桶最大偏差 {max(diffs):.6f}" if diffs else "")
    # 首桶：原始实现只统计区间起点之后的那半天，日线表用整天 → 允许小偏差
    check("⑧ 首桶（残日 vs 整天）偏差 < 0.05", boundary_diff < 0.05,
          f"{boundary_diff:.3f}")

    dash = m.get_dashboard_data(hours=24)
    check("⑨ 首页总记录数 == COUNT(*)",
          dash["total_records"] == raw_total, f"{dash['total_records']:,} vs {raw_total:,}")
    conn.close()

    # 二次构造不重复重建（自愈逻辑应短路）
    t0 = time.perf_counter()
    PriceMapper()
    second_ms = (time.perf_counter() - t0) * 1000
    check("⑩ 二次启动不重复重建", second_ms < 300, f"{second_ms:.0f}ms")

    print(f"\n{'全部通过' if ok else '存在失败项'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
