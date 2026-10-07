import json
import sqlite3
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum

import requests

from mapper.ai_stats_mapper import AiStatsMapper
from service.system_settings_service import SystemSettingsService
from utils.logger import get_logger
from utils.time_utils import now

logger = get_logger("ModelPool")

# HTTP 状态码 → 可读含义
_HTTP_STATUS_MAP: dict[int, str] = {
    400: "请求参数错误",
    401: "API Key 无效或未授权",
    403: "访问被禁止（权限不足或账户欠费）",
    404: "API 端点不存在",
    408: "请求超时",
    429: "请求频率超限（Rate Limit）",
    500: "服务器内部错误",
    502: "网关错误",
    503: "服务不可用（临时过载或维护中）",
    504: "网关超时",
}


def _describe_http_status(code: int) -> str:
    return _HTTP_STATUS_MAP.get(code, "未知 HTTP 错误")


class ErrorClass(Enum):
    """失败原因分类 —— 决定重试与冷却策略"""

    RATE_LIMITED = "rate_limited"  # 429：账号级限速，重试只会更糟
    OVERLOADED = "overloaded"  # 5xx：临时过载
    TRANSIENT = "transient"  # 超时 / 网络抖动
    FATAL = "fatal"  # 400/401/403/404 / 内容审核：重试无意义


@dataclass
class ModelResult:
    success: bool
    content: str | None = None
    provider: str | None = None
    model: str | None = None
    from_cache: bool = False
    error: str | None = None
    retryable: bool = True
    raw_response: str | None = None
    error_class: ErrorClass | None = None
    #: 服务端要求的等待秒数（Retry-After）。同步睡眠封顶后，超出部分折算进冷却。
    retry_after: float | None = None
    """
    是否可重试。
    False 表示错误是确定性的（内容被审核、API Key 无效、权限不足等），
    重试也不会成功，应直接跳到下一个模型。
    """


@dataclass
class Cooldown:
    """冷却状态：到期时间 + 连续触发次数（用于指数升级）"""

    until: datetime
    strikes: int = 1


# ---- 冷却参数 ----
#: 模型级 429 冷却基准（秒）。连续触发按 ×2 升级：60 → 120 → 240 …
_MODEL_COOLDOWN_BASE = 60.0
#: 供应商级 429 冷却基准（秒）。限速通常是账号级的，同 Key 跳模型没用。
_PROVIDER_COOLDOWN_BASE = 120.0
#: 冷却上限（模型与供应商共用）
_COOLDOWN_MAX = 1800.0
#: 供应商内多少个模型触发 429 后，整级冷却
_PROVIDER_THROTTLE_TRIP = 2
#: 过载 / 网络类失败的模型冷却（秒，不升级）
_OVERLOAD_COOLDOWN = 30.0
#: Retry-After 同步睡眠封顶（秒）。超出部分折算进冷却时长，不再阻塞监控循环。
_RETRY_AFTER_SLEEP_CAP = 5.0


def _escalate(previous: Cooldown | None, base: float, hint: float = 0.0) -> Cooldown:
    """基于上次冷却计算下一次：连续触发 ×2 升级，上限封顶。

    `hint`（Retry-After）低于基准时忽略；高于基准时以其为底，保证尊重服务端要求。
    """
    effective_base = max(base, hint)
    if previous is not None and now() < previous.until:
        strikes = previous.strikes + 1
    else:
        strikes = 1
    duration = min(effective_base * (2 ** (strikes - 1)), _COOLDOWN_MAX)
    return Cooldown(until=now() + timedelta(seconds=duration), strikes=strikes)


class ModelPool:
    """多级 AI 模型池

    L1: 智能重试（指数退避 + 尊重 Retry-After，睡眠封顶）
    L2: 同平台模型降级（glm-4.7-flash → glm-4-flash）
    L3: 跨供应商故障转移（智谱 → 硅基流动 → ...）
    L4: 优雅降级（返回缓存 / 标记不可用）

    限速惩罚（叠加在 L1-L3 之上）：
    - 429 不再原地重试，直接跳级；触发模型进入冷却（60s 起，连续触发 ×2，上限 30min）；
    - 同一供应商累计 2 个模型触发 429 → 整级冷却（120s 起，同样升级）——
      限速多半是账号级的，同 Key 换模型没有意义；
    - 5xx / 超时 / 网络类失败保留 1 次快速重试，失败后模型短冷却 30s；
    - 冷却到期后**自动恢复原有优先级顺序**，flap 自限（立刻再 429 会立刻再冷却）。
    """

    def __init__(self, providers: list[dict]):
        self.providers = providers
        self.settings = SystemSettingsService()
        ai_config = self.settings.get_ai_config()
        self.max_retries = ai_config.get("max_retries", 3)
        self.retry_base_delay = ai_config.get("retry_base_delay", 1.0)
        self.cache_ttl = timedelta(minutes=ai_config.get("cache_ttl_minutes", 60))
        self._ai_config = ai_config
        self._cache: dict[str, tuple[datetime, ModelResult]] = {}
        # 冷却状态（内存态，进程重启清零）：key = (provider_name, model_name) / provider_name
        self._model_cooldowns: dict[tuple[str, str], Cooldown] = {}
        self._provider_cooldowns: dict[str, Cooldown] = {}
        self._provider_throttles: dict[str, int] = {}
        self._stats_mapper = AiStatsMapper()
        self._stats_mapper.init_tables()

    # ==================== 入口 ====================

    def call(
        self, system_prompt: str, user_prompt: str, cache_key: str = "default"
    ) -> ModelResult:
        """多级调用入口 — 按 L1→L2→L3→L4 依次尝试，冷却中的模型/供应商跳过"""
        start_time = time.monotonic()
        for provider_cfg in self.providers:
            provider_name = provider_cfg["name"]
            if not provider_cfg.get("api_key"):
                logger.debug(f"跳过供应商 [{provider_name}]：未配置 API Key")
                continue

            provider_cd = self._provider_cooldowns.get(provider_name)
            if provider_cd is not None and now() < provider_cd.until:
                logger.debug(
                    f"跳过供应商 [{provider_name}]：限速冷却至 "
                    f"{provider_cd.until:%H:%M:%S}（第 {provider_cd.strikes} 级）"
                )
                continue

            for model in provider_cfg.get("models", []):
                model_cd = self._model_cooldowns.get((provider_name, model))
                if model_cd is not None and now() < model_cd.until:
                    logger.debug(
                        f"跳过 [{provider_name}]/{model}：冷却至 {model_cd.until:%H:%M:%S}"
                    )
                    continue

                logger.info(f"尝试 [{provider_name}]/{model} ...")
                # L1: 智能重试
                model_start = time.monotonic()
                result = self._retry_with_backoff(
                    provider_cfg, model, system_prompt, user_prompt
                )
                if result.success:
                    logger.info(f"[{provider_name}]/{model} 调用成功")
                    self._on_provider_success(provider_name)
                    self._update_cache(cache_key, result)
                    self._log_call(result, model_start)
                    return result

                # 失败：记录本次失败（延迟只计本模型耗时），按错误类别施加冷却
                self._log_call(result, model_start)
                self._apply_penalty(provider_name, model, result)
                logger.warning(f"[{provider_name}]/{model} 失败 → 尝试下一个候选")

            logger.warning(f"供应商 [{provider_name}] 全部失败 → 尝试下一个供应商")

        # L4: 优雅降级
        result = self._graceful_degradation(cache_key)
        self._log_call(result, start_time)
        return result

    # ==================== 冷却 ====================

    def _apply_penalty(
        self, provider_name: str, model: str, result: ModelResult
    ) -> None:
        """按错误类别施加模型级 / 供应商级冷却"""
        klass = result.error_class
        if klass is ErrorClass.RATE_LIMITED:
            key = (provider_name, model)
            self._model_cooldowns[key] = _escalate(
                self._model_cooldowns.get(key),
                _MODEL_COOLDOWN_BASE,
                hint=result.retry_after or 0.0,
            )
            cooldown = self._model_cooldowns[key]
            logger.warning(
                f"[{provider_name}]/{model} 限速冷却 "
                f"{(cooldown.until - now()).total_seconds():.0f}s"
                f"（第 {cooldown.strikes} 级）"
            )

            throttles = self._provider_throttles.get(provider_name, 0) + 1
            if throttles >= _PROVIDER_THROTTLE_TRIP:
                self._provider_cooldowns[provider_name] = _escalate(
                    self._provider_cooldowns.get(provider_name),
                    _PROVIDER_COOLDOWN_BASE,
                )
                pcd = self._provider_cooldowns[provider_name]
                self._provider_throttles[provider_name] = 0
                logger.warning(
                    f"供应商 [{provider_name}] 累计 {throttles} 个模型限速，"
                    f"整级冷却 {(pcd.until - now()).total_seconds():.0f}s"
                    f"（第 {pcd.strikes} 级）"
                )
            else:
                self._provider_throttles[provider_name] = throttles
            return

        if klass in (ErrorClass.OVERLOADED, ErrorClass.TRANSIENT):
            self._model_cooldowns[(provider_name, model)] = Cooldown(
                until=now() + timedelta(seconds=_OVERLOAD_COOLDOWN), strikes=1
            )
            logger.info(
                f"[{provider_name}]/{model} 过载/网络失败，短冷却 {_OVERLOAD_COOLDOWN:.0f}s"
            )

        # FATAL：确定性失败，不冷却（下一轮调用仍会尝试，由结果本身决定）

    def _on_provider_success(self, provider_name: str) -> None:
        """成功即清零该供应商的限速计数与冷却，恢复原有优先级"""
        self._provider_throttles.pop(provider_name, None)
        self._provider_cooldowns.pop(provider_name, None)
        for key in [k for k in self._model_cooldowns if k[0] == provider_name]:
            del self._model_cooldowns[key]

    # ==================== L1: 重试 ====================

    def _retry_with_backoff(
        self, provider: dict, model: str, system_prompt: str, user_prompt: str
    ) -> ModelResult:
        """L1: 按错误类别决定原地重试次数。

        限速（429）**不原地重试**——重试只会再次 429 并继续消耗配额；
        过载 / 网络类保留最多 1 次快速重试；确定性失败直接返回。
        """
        last_error = None
        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                delay = self.retry_base_delay * (2 ** (attempt - 1))
                logger.warning(
                    f"[{provider['name']}]/{model} 第 {attempt}/{self.max_retries} 次重试，"
                    f"等待 {delay:.1f}s"
                )
                time.sleep(delay)

            try:
                result = self._call_single(provider, model, system_prompt, user_prompt)
                if result.success:
                    if attempt > 0:
                        logger.info(
                            f"[{provider['name']}]/{model} 第 {attempt} 次重试成功"
                        )
                    return result
                klass = result.error_class
                if klass in (ErrorClass.RATE_LIMITED, ErrorClass.FATAL):
                    logger.warning(
                        f"[{provider['name']}]/{model} "
                        f"{'限速' if klass is ErrorClass.RATE_LIMITED else '确定性错误'}，"
                        "跳过原地重试"
                    )
                    return result
                last_error = result.error
                # 过载 / 网络类：只保留 1 次快速重试
                if attempt >= 1:
                    return result
            except Exception as e:  # noqa: BLE001
                last_error = str(e)
                logger.warning(
                    f"[{provider['name']}]/{model} 未捕获异常 | "
                    f"类型={type(e).__name__} | 详情={e}"
                )
                if attempt >= 1:
                    break

        logger.error(
            f"[{provider['name']}]/{model} 原地重试耗尽 | 最后错误={last_error}"
        )
        return ModelResult(
            success=False,
            provider=provider["name"],
            model=model,
            error=last_error or "未知错误",
            error_class=ErrorClass.TRANSIENT,
        )

    # ==================== 单次调用 ====================

    def _call_single(
        self, provider: dict, model: str, system_prompt: str, user_prompt: str
    ) -> ModelResult:
        """单次 API 调用"""
        headers = {
            "Authorization": f"Bearer {provider['api_key']}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "temperature": self._ai_config["temperature"],
            "max_tokens": self._ai_config["max_tokens"],
        }
        label = f"[{provider['name']}]/{model}"

        if self._ai_config["prompt_check"]:
            logger.debug(
                f"{label} 发送请求\n"
                f"--- SystemPrompt ---\n{system_prompt}\n"
                f"--- UserPrompt ---\n{user_prompt}"
            )

        try:
            resp = requests.post(
                provider["api_url"],
                headers=headers,
                json=payload,
                timeout=provider.get("timeout", 30),
            )

            if resp.status_code == 200:
                data = resp.json()
                if "error" in data:
                    err_detail = data["error"]
                    err_msg = (
                        err_detail.get("message", "unknown")
                        if isinstance(err_detail, dict)
                        else str(err_detail)
                    )
                    err_code = (
                        err_detail.get("code", "")
                        if isinstance(err_detail, dict)
                        else ""
                    )
                    logger.warning(
                        f"{label} [API] 返回业务错误"
                        f" | code={err_code} | message={err_msg}"
                    )
                    return ModelResult(
                        success=False,
                        provider=provider["name"],
                        model=model,
                        error=f"API 业务错误(code={err_code}): {err_msg}",
                        retryable=False,
                        error_class=ErrorClass.FATAL,
                    )
                choice = data["choices"][0]
                finish_reason = choice.get("finish_reason", "")
                if finish_reason == "length":
                    logger.warning(
                        f"{label} AI 响应因长度限制被截断，考虑增大 max_tokens"
                    )
                return ModelResult(
                    success=True,
                    content=choice["message"]["content"],
                    provider=provider["name"],
                    model=model,
                    raw_response=resp.text,
                )

            # 非 200 响应
            status_desc = _describe_http_status(resp.status_code)
            body_preview = resp.text[:200].replace("\n", " ")
            logger.warning(
                f"{label} [HTTP {resp.status_code}] {status_desc}"
                f" | 响应体={body_preview}"
            )

            retry_after: float | None = None
            raw_retry_after = resp.headers.get("Retry-After")
            if raw_retry_after:
                try:
                    retry_after = float(raw_retry_after)
                except ValueError:
                    retry_after = None

            if retry_after is not None:
                wait = min(retry_after, _RETRY_AFTER_SLEEP_CAP)
                capped = "" if wait >= retry_after else "（封顶）"
                logger.info(
                    f"{label} 服务端要求等待 {retry_after:.0f}s，"
                    f"同步等待 {wait:.0f}s{capped}"
                )
                time.sleep(wait)

            error_class = _classify_http_status(resp.status_code)
            retryable = error_class is not ErrorClass.FATAL
            return ModelResult(
                success=False,
                provider=provider["name"],
                model=model,
                error=f"HTTP {resp.status_code} ({status_desc}): {body_preview}",
                retryable=retryable,
                error_class=error_class,
                retry_after=retry_after,
            )

        except requests.Timeout:
            logger.warning(
                f"{label} [TIMEOUT] 请求超时"
                f" | URL={provider['api_url']}"
                f" | 超时设置={provider.get('timeout', 30)}s"
            )
            return ModelResult(
                success=False,
                provider=provider["name"],
                model=model,
                error=f"请求超时({provider.get('timeout', 30)}s)",
                error_class=ErrorClass.TRANSIENT,
            )

        except requests.ConnectionError as e:
            logger.error(
                f"{label} [NETWORK] 网络连接失败 | URL={provider['api_url']} | 原因={e}"
            )
            return ModelResult(
                success=False,
                provider=provider["name"],
                model=model,
                error=f"网络连接失败: {e}",
                error_class=ErrorClass.TRANSIENT,
            )

        except requests.RequestException as e:
            logger.error(
                f"{label} [REQUEST] 请求异常 | 类型={type(e).__name__} | 详情={e}"
            )
            return ModelResult(
                success=False,
                provider=provider["name"],
                model=model,
                error=f"请求异常({type(e).__name__}): {e}",
                error_class=ErrorClass.TRANSIENT,
            )

    # ==================== 缓存与降级 ====================

    def _update_cache(self, key: str, result: ModelResult):
        self._cache[key] = (now(), result)

    def _graceful_degradation(self, cache_key: str) -> ModelResult:
        """L4: 优雅降级"""
        if cache_key in self._cache:
            cached_time, cached_result = self._cache[cache_key]
            if now() - cached_time < self.cache_ttl:
                age = (now() - cached_time).total_seconds()
                logger.warning(
                    f"[L4] 所有模型均不可用，返回缓存结果"
                    f" | 缓存年龄={age:.0f}s"
                    f" | 原始来源={cached_result.provider}/{cached_result.model}"
                )
                # 不改动缓存里的对象，避免下次降级时年龄标记失真
                return replace(cached_result, from_cache=True)

        logger.error(
            "[L4] 所有模型均不可用且无有效缓存，AI 分析暂不可用"
            f" | 已尝试供应商数={len(self.providers)}"
            f" | 缓存 TTL={self.cache_ttl}"
        )
        return ModelResult(
            success=False, error="AI 分析暂不可用：所有模型供应商均调用失败"
        )

    def _log_call(self, result: ModelResult, start_time: float) -> None:
        latency_ms = int((time.monotonic() - start_time) * 1000)
        prompt_tokens, completion_tokens, total_tokens = self._extract_tokens(
            result.raw_response
        )
        try:
            self._stats_mapper.insert_log(
                provider_name=result.provider or "unknown",
                model_name=result.model or "unknown",
                call_time=now(),
                success=result.success,
                latency_ms=latency_ms,
                error_reason=result.error[:200] if result.error else None,
                from_cache=result.from_cache,
                triggered_alerts=None,
                raw_response=result.raw_response,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )
        except sqlite3.Error:
            logger.warning("AI 调用统计写入失败！")

    @staticmethod
    def _extract_tokens(raw_response: str | None) -> tuple[int, int, int]:
        if not raw_response:
            return 0, 0, 0
        try:
            data = json.loads(raw_response)
            usage = data.get("usage", {})
            return (
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                usage.get("total_tokens", 0),
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            return 0, 0, 0


def _classify_http_status(status_code: int) -> ErrorClass:
    """HTTP 状态码 → 错误分类"""
    if status_code == 429:
        return ErrorClass.RATE_LIMITED
    if status_code in (400, 401, 403, 404):
        return ErrorClass.FATAL
    if status_code >= 500:
        return ErrorClass.OVERLOADED
    return ErrorClass.TRANSIENT
