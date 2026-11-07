"""在线节假日源探测脚本（P0#4 决策依据）。

探测主流免费中国节假日 API 的可用性、数据结构与覆盖年份，
输出结论供 `infra-refactor-plan.md §1` 的 OnlineCalendarProvider 决策使用。

用法：
    cd backend && uv run python scripts/probe_holiday_apis.py

探测源：
    1. timor.tech  /api/holiday/info/{date}   单日查询（免费、无 Key）
    2. timor.tech  /api/holiday/year/{year}   全年批量（缓存落库的候选源）
    3. haoshenqi   /holiday?date={date}       备选对照（社区接口，稳定性未知）

判定用例（国务院公告口径，与 chinese-calendar 一致）：
    - 2026-10-01 国庆节         → 休假日
    - 2025-10-11 周六调休上班   → 工作日（周末但上班）
    - 2026-01-01 元旦           → 休假日
"""

import json
import sys

import requests

TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}
PROBES = [
    ("2026-10-01", True, "国庆节"),
    ("2025-10-11", False, "周六调休上班"),
    ("2026-01-01", True, "元旦"),
]


def _get(url: str) -> requests.Response | None:
    """带 UA 与一次重试的 GET"""
    for attempt in range(2):
        try:
            resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
            resp.raise_for_status()
            return resp
        except requests.RequestException:
            if attempt == 1:
                return None
    return None


def _check(name: str, ok: bool, detail: str) -> dict:
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    return {"name": name, "ok": ok, "detail": detail}


def probe_timor_info() -> dict:
    """timor.tech 单日接口"""
    url = "https://timor.tech/api/holiday/info/2026-10-01"
    resp = _get(url)
    if resp is None:
        return _check("timor/info", False, "请求失败（超时/反爬）")
    data = resp.json()
    ok = data.get("code") == 0
    holiday = data.get("holiday", {}) or {}
    detail = (
        f"code={data.get('code')} date={data.get('date', {}).get('week')} "
        f"holiday={json.dumps(holiday, ensure_ascii=False)[:120]}"
    )
    return _check("timor/info 可达且返回结构", ok, detail)


def probe_timor_year(year: int) -> dict:
    """timor.tech 全年接口：验证覆盖"""
    url = f"https://timor.tech/api/holiday/year/{year}"
    resp = _get(url)
    if resp is None:
        return _check(f"timor/year/{year}", False, "请求失败（超时/反爬）")
    data = resp.json()
    keys = data.get("holiday") or {}
    return _check(
        f"timor/year/{year} 覆盖",
        bool(keys),
        f"共 {len(keys)} 个节假日条目，样例：{list(keys)[:3]}",
    )


def probe_timor_verdicts() -> list[dict]:
    """用已知用例验证 timor 判定方向是否与国务院口径一致"""
    results = []
    for day_str, expect_holiday, label in PROBES:
        url = f"https://timor.tech/api/holiday/info/{day_str}"
        resp = _get(url)
        if resp is None:
            results.append(_check(f"timor 判定 {day_str}", False, "请求失败（超时/反爬）"))
            continue
        data = resp.json()
        is_holiday = bool(data.get("holiday"))
        results.append(
            _check(
                f"timor 判定 {day_str}（{label}）",
                is_holiday == expect_holiday,
                f"期望{'假日' if expect_holiday else '工作日'}，"
                f"实际{'假日' if is_holiday else '非假日'}",
            )
        )
    return results


def probe_haoshenqi() -> list[dict]:
    """haoshenqi：可达性 + 判定方向 + 年份覆盖（status!=0 即非纯工作日）"""
    results = []
    url = "https://api.haoshenqi.top/holiday?date=2026-10-01"
    resp = _get(url)
    if resp is None:
        results.append(_check("haoshenqi（对照）", False, "请求失败"))
        return results
    sample = resp.json()
    results.append(
        _check(
            "haoshenqi 可达",
            True,
            f"字段={list(sample)[:8]} status 含义待验证（3=假日?）",
        )
    )

    for day_str, expect_holiday, label in PROBES:
        resp = _get(f"https://api.haoshenqi.top/holiday?date={day_str}")
        if resp is None:
            results.append(_check(f"haoshenqi 判定 {day_str}", False, "请求失败"))
            continue
        data = resp.json()
        # 响应形态不统一：部分日期返回对象，部分返回列表（取与日期匹配或首个元素）
        if isinstance(data, list):
            data = next(
                (item for item in data if item.get("date") == day_str),
                data[0] if data else {},
            )
        status = data.get("status")
        # status: 0=工作日 1=周末 2=调休上班 3=法定假日（社区口径，按此验证）
        is_holiday = status == 3
        is_workday_weekend = status in (0, 2)
        ok = is_holiday if expect_holiday else is_workday_weekend
        results.append(
            _check(
                f"haoshenqi 判定 {day_str}（{label}）",
                ok,
                f"status={status}",
            )
        )

    # 年份覆盖：2027 安排是否已发布
    for year in (2026, 2027):
        resp = _get(f"https://api.haoshenqi.top/holiday?date={year}-06-01")
        if resp is None:
            results.append(_check(f"haoshenqi {year} 年覆盖", False, "请求失败"))
            continue
        data = resp.json()
        if isinstance(data, list):
            data = data[0] if data else {}
        results.append(
            _check(
                f"haoshenqi {year} 年覆盖",
                "status" in data,
                f"{year}-06-01 status={data.get('status')}",
            )
        )
    return results


def main() -> int:
    print("=" * 60)
    print("在线节假日源探测")
    print("=" * 60)
    results: list[dict] = []
    results.append(probe_timor_info())
    for year in (2025, 2026, 2027):
        results.append(probe_timor_year(year))
    results.extend(probe_timor_verdicts())
    results.extend(probe_haoshenqi())

    passed = sum(1 for r in results if r["ok"])
    print("-" * 60)
    print(f"{passed}/{len(results)} 项通过")
    haoshenqi_core = [r for r in results if r["name"].startswith("haoshenqi 判定")]
    haoshenqi_ok = bool(haoshenqi_core) and all(r["ok"] for r in haoshenqi_core)
    verdict = (
        "haoshenqi 判定方向全部正确，可作为 OnlineCalendarProvider 首选；timor 需再评估"
        if haoshenqi_ok
        else "所有在线源均不可靠，暂缓在线源，维持 lib → weekly 回退"
    )
    print(f"结论：{verdict}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
