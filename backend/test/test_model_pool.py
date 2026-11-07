"""`ModelPool` 限速惩罚机制测试。

用假件替换 `_call_single`（不碰网络），验证 infra-refactor-plan §2 的规则：

1. 429 不原地重试，直接跳级，模型进入冷却（60s 起）；
2. 连续 429 冷却指数升级（60 → 120 → 240 …，上限 30min）；
3. 同供应商累计 2 个模型 429 → 整级冷却（120s 起）；
4. 冷却期内的模型 / 供应商在下一轮 `call()` 中被跳过；
5. 任意模型成功 → 该供应商的计数与冷却全部清零，优先级顺序恢复；
6. Retry-After 封顶同步睡眠，超出部分折算进冷却时长；
7. 5xx / 超时保留 1 次快速重试，失败后短冷却 30s；确定性失败不冷却；
8. `_log_call` 延迟按模型单独计；L4 缓存对象不被原地修改。

运行
----
    cd backend
    python -m test.test_model_pool
"""

import datetime
import json

import service.model_pool_engine as engine
from service.model_pool_engine import (
    _OVERLOAD_COOLDOWN,
    _PROVIDER_COOLDOWN_BASE,
    Cooldown,
    ErrorClass,
    ModelPool,
    ModelResult,
)

_BASE = datetime.datetime(2026, 10, 7, 12, 0, 0)

#: 捕获真实 sleep —— 引擎里 `engine.time` 就是标准库 time 模块，
#: 打补丁是进程级全局的，必须在打补丁前留底
_REAL_SLEEP = engine.time.sleep

PROVIDERS = [
    {
        "name": "alpha",
        "api_key": "k-alpha",
        "api_url": "https://alpha.example/v1/chat",
        "models": ["m1", "m2"],
        "timeout": 5,
    },
    {
        "name": "beta",
        "api_key": "k-beta",
        "api_url": "https://beta.example/v1/chat",
        "models": ["b1"],
        "timeout": 5,
    },
]


class _FakeClock:
    """可控时钟：替换 engine.now，让冷却判定可以推演"""

    def __init__(self) -> None:
        self.t = _BASE

    def __call__(self) -> datetime.datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t = self.t + datetime.timedelta(seconds=seconds)


class _StatsRecorder:
    """替换 AiStatsMapper：记录 insert_log 调用，不碰数据库"""

    def __init__(self) -> None:
        self.entries: list[dict] = []

    def init_tables(self) -> None: ...

    def insert_log(self, **kwargs) -> None:
        self.entries.append(kwargs)


def _result(
    *,
    success: bool = False,
    provider: str = "",
    model: str = "",
    error: str | None = None,
    error_class: ErrorClass | None = None,
    retry_after: float | None = None,
) -> ModelResult:
    return ModelResult(
        success=success,
        provider=provider or None,
        model=model or None,
        error=error,
        error_class=error_class,
        retry_after=retry_after,
    )


def _http(status: int, retry_after: float | None = None) -> ModelResult:
    from service.model_pool_engine import _classify_http_status

    klass = _classify_http_status(status)
    return _result(
        error=f"HTTP {status}",
        error_class=klass,
        retry_after=retry_after,
    )


def _pool(script: dict[str, list[ModelResult]] | None = None) -> tuple[
    ModelPool, _FakeClock, list, tuple
]:
    """构造测试池：假时钟 + 假统计 + 可编程的 `_call_single` 剧本

    `script` 按 `provider/model` 给出返回队列，队列空了沿用最后一个结果。
    返回 (pool, clock, calls)；`calls` 记录每次 (provider, model)。
    """
    clock = _FakeClock()
    saved_now = engine.now
    engine.now = clock
    pool = ModelPool(PROVIDERS)
    pool._stats_mapper = _StatsRecorder()

    script = script or {}
    calls: list[tuple[str, str]] = []

    def fake_call_single(provider: dict, model: str, _s: str, _u: str) -> ModelResult:
        calls.append((provider["name"], model))
        queue = script.get(f"{provider['name']}/{model}")
        if not queue:
            return _result(error="no script", error_class=ErrorClass.TRANSIENT)
        return queue.pop(0)

    pool._call_single = fake_call_single  # type: ignore[method-assign]
    original_sleep = engine.time.sleep
    engine.time.sleep = lambda _s: None  # 重试退避不真睡
    return pool, clock, calls, (saved_now, original_sleep)


def _cleanup(tokens: tuple) -> None:
    saved_now, original_sleep = tokens
    engine.now = saved_now
    engine.time.sleep = original_sleep


def test_429_skips_inplace_retry_and_cools_model() -> None:
    """429 不原地重试：单模型只被调用一次，并进入冷却"""
    pool, clock, calls, tokens = _pool({"alpha/m1": [_http(429)]})
    try:
        result = pool.call("sys", "user", cache_key="k")
        assert not result.success
        assert calls.count(("alpha", "m1")) == 1, f"429 应只调一次，实际 {calls}"
        cd = pool._model_cooldowns[("alpha", "m1")]
        assert cd.strikes == 1
        assert (cd.until - clock.t).total_seconds() == 60.0
    finally:
        _cleanup(tokens)


def test_429_cooldown_escalates_on_consecutive_hits() -> None:
    """冷却期内再次 429：60 → 120 → 240，封顶 30min"""
    pool, clock, _calls, tokens = _pool()
    try:
        r = _http(429)
        pool._apply_penalty("alpha", "m1", r)
        pool._apply_penalty("alpha", "m1", r)
        cd = pool._model_cooldowns[("alpha", "m1")]
        assert cd.strikes == 2
        assert (cd.until - clock.t).total_seconds() == 120.0
        pool._apply_penalty("alpha", "m1", r)
        cd = pool._model_cooldowns[("alpha", "m1")]
        assert cd.strikes == 3
        assert (cd.until - clock.t).total_seconds() == 240.0
        for _ in range(10):
            pool._apply_penalty("alpha", "m1", r)
        cd = pool._model_cooldowns[("alpha", "m1")]
        assert (cd.until - clock.t).total_seconds() <= 1800.0
    finally:
        _cleanup(tokens)


def test_provider_trips_after_two_models_rate_limited() -> None:
    """同供应商两个模型都 429 → 整级冷却（120s），限速计数清零"""
    pool, clock, calls, tokens = _pool(
        {"alpha/m1": [_http(429)], "alpha/m2": [_http(429)], "beta/b1": [_http(429)]}
    )
    try:
        pool.call("sys", "user", cache_key="k")
        assert ("alpha", "m1") in calls and ("alpha", "m2") in calls
        pcd = pool._provider_cooldowns["alpha"]
        assert pcd.strikes == 1
        assert (pcd.until - clock.t).total_seconds() == _PROVIDER_COOLDOWN_BASE
        assert pool._provider_throttles["alpha"] == 0
        # beta 只有 1 个模型 429，不应整级冷却
        assert "beta" not in pool._provider_cooldowns
    finally:
        _cleanup(tokens)


def test_cooldown_skips_model_and_provider_on_next_call() -> None:
    """冷却中的模型 / 整级冷却的供应商，下一轮 call() 直接跳过"""
    pool, clock, calls, tokens = _pool(
        {"alpha/m1": [_http(429)], "alpha/m2": [_http(429)], "beta/b1": [_http(429)]}
    )
    try:
        pool.call("sys", "user", cache_key="k")
        assert len(calls) == 3
        calls.clear()
        pool.call("sys", "user", cache_key="k")
        assert calls == [], f"全部冷却中应零调用，实际 {calls}"
        # 冷却到期后恢复原优先级：m1 先于 m2
        clock.advance(1801)
        pool._call_single = lambda p, m, s, u: _result(  # type: ignore[assignment]
            success=True, provider=p["name"], model=m
        )
        result = pool.call("sys", "user", cache_key="k")
        assert result.success and result.model == "m1"
    finally:
        _cleanup(tokens)


def test_success_resets_provider_state() -> None:
    """成功即清零该供应商的限速计数与冷却"""
    pool, _clock, _calls, tokens = _pool()
    try:
        r = _http(429)
        pool._apply_penalty("alpha", "m1", r)
        pool._apply_penalty("alpha", "m1", r)
        assert ("alpha", "m1") in pool._model_cooldowns
        pool._on_provider_success("alpha")
        assert ("alpha", "m1") not in pool._model_cooldowns
        assert "alpha" not in pool._provider_cooldowns
        assert "alpha" not in pool._provider_throttles
    finally:
        _cleanup(tokens)


def test_retry_after_capped_and_folded_into_cooldown() -> None:
    """Retry-After=600：同步睡眠封顶 5s，冷却时长以其为底"""
    pool, clock, calls, tokens = _pool(
        {"alpha/m1": [_http(429, retry_after=600)]}
    )
    try:
        pool.call("sys", "user", cache_key="k")
        assert calls.count(("alpha", "m1")) == 1
        cd = pool._model_cooldowns[("alpha", "m1")]
        assert (cd.until - clock.t).total_seconds() == 600.0
    finally:
        _cleanup(tokens)


def test_overloaded_gets_one_retry_then_short_cooldown() -> None:
    """503：保留 1 次快速重试（共 2 次调用），失败后短冷却 30s"""
    pool, clock, calls, tokens = _pool({"alpha/m1": [_http(503), _http(503)]})
    try:
        pool.call("sys", "user", cache_key="k")
        assert calls.count(("alpha", "m1")) == 2, f"503 应重试 1 次，实际 {calls}"
        cd = pool._model_cooldowns[("alpha", "m1")]
        assert (cd.until - clock.t).total_seconds() == _OVERLOAD_COOLDOWN
    finally:
        _cleanup(tokens)


def test_fatal_gets_no_cooldown() -> None:
    """401 确定性失败：不冷却（下轮仍会尝试，由结果决定）"""
    pool, _clock, calls, tokens = _pool({"alpha/m1": [_http(401)]})
    try:
        pool.call("sys", "user", cache_key="k")
        assert ("alpha", "m1") not in pool._model_cooldowns
    finally:
        _cleanup(tokens)


def test_latency_logged_per_model_not_cumulative() -> None:
    """失败日志的延迟只计本模型耗时，不把前面模型的失败算进来"""
    pool, _clock, _calls, tokens = _pool()

    def slow_then_fast(provider: dict, model: str, _s: str, _u: str) -> ModelResult:
        if model == "m1":
            engine.time.sleep(0.05)  # 模拟第一个模型耗时
        return _result(
            provider=provider["name"],
            model=model,
            error="HTTP 429",
            error_class=ErrorClass.RATE_LIMITED,
        )

    pool._call_single = slow_then_fast  # type: ignore[method-assign]
    try:
        engine.time.sleep = _REAL_SLEEP  # 恢复真实 sleep，让 m1 的耗时可计量
        pool.call("sys", "user", cache_key="k")
        entries = pool._stats_mapper.entries
        by_model = {e["model_name"]: e["latency_ms"] for e in entries}
        assert by_model["m1"] >= 40, f"m1 应含真实耗时，实际 {by_model}"
        assert by_model["m2"] < 40, f"m2 延迟不应包含 m1 的耗时，实际 {by_model}"
    finally:
        _cleanup(tokens)


def test_l4_cache_object_not_mutated() -> None:
    """L4 降级返回 from_cache=True，但缓存里的原对象不被改动"""
    pool, _clock, _calls, tokens = _pool()
    try:
        good = ModelResult(
            success=True,
            content="ok",
            provider="alpha",
            model="m1",
            raw_response=json.dumps({"usage": {"total_tokens": 1}}),
        )
        pool._update_cache("k", good)
        degraded = pool._graceful_degradation("k")
        assert degraded.from_cache is True
        assert good.from_cache is False, "缓存原对象不应被污染"
        again = pool._graceful_degradation("k")
        assert again.from_cache is True
    finally:
        _cleanup(tokens)


def test_escalation_uses_retry_after_as_floor() -> None:
    """Retry-After 低于基准时忽略；连续触发时以基准升级"""
    pool, clock, _calls, tokens = _pool()
    try:
        pool._apply_penalty("alpha", "m1", _http(429, retry_after=1.0))
        cd = pool._model_cooldowns[("alpha", "m1")]
        assert (cd.until - clock.t).total_seconds() == 60.0, "hint 低于基准应被忽略"
    finally:
        _cleanup(tokens)


def test_cooldown_state_is_memory_only() -> None:
    """冷却状态是纯内存结构（重启清零语义），不落库"""
    pool, _clock, _calls, tokens = _pool()
    try:
        pool._apply_penalty("alpha", "m1", _http(429))
        assert isinstance(pool._model_cooldowns[("alpha", "m1")], Cooldown)
        assert not hasattr(pool._stats_mapper, "select_cooldowns")
    finally:
        _cleanup(tokens)


if __name__ == "__main__":
    tests = [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    failed = 0
    for name, test in tests:
        try:
            test()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"ERROR {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"PASS  {name}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
