import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import requests

from config import CHINA_TZ
from mapper.ai_stats_mapper import AiStatsMapper
from service.system_settings_service import SystemSettingsService
from utils.logger import get_logger

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


@dataclass
class ModelResult:
    success: bool
    content: str | None = None
    provider: str | None = None
    model: str | None = None
    from_cache: bool = False
    error: str | None = None
    retryable: bool = True
    """
    是否可重试。
    False 表示错误是确定性的（内容被审核、API Key 无效、权限不足等），
    重试也不会成功，应直接跳到下一个模型。
    """


class ModelPool:
    """多级 AI 模型池

    L1: 智能重试（指数退避 + 尊重 Retry-After）
    L2: 同平台模型降级（glm-4.7-flash → glm-4-flash）
    L3: 跨供应商故障转移（智谱 → 硅基流动 → ...）
    L4: 优雅降级（返回缓存 / 标记不可用）
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
        self._stats_mapper = AiStatsMapper()
        self._stats_mapper.init_tables()

    def call(
        self, system_prompt: str, user_prompt: str, cache_key: str = "default"
    ) -> ModelResult:
        """多级调用入口 — 按 L1→L2→L3→L4 依次尝试"""
        start_time = time.monotonic()
        for provider_cfg in self.providers:
            if not provider_cfg.get("api_key"):
                logger.debug(f"跳过供应商 [{provider_cfg['name']}]：未配置 API Key")
                continue

            for model in provider_cfg.get("models", []):
                logger.info(f"尝试 [{provider_cfg['name']}]/{model} ...")
                # L1: 智能重试
                result = self._retry_with_backoff(
                    provider_cfg, model, system_prompt, user_prompt
                )
                if result.success:
                    logger.info(f"[{provider_cfg['name']}]/{model} 调用成功")
                    self._update_cache(cache_key, result)
                    self._log_call(result, start_time)
                    return result
                # L2: 同平台下一个模型（先记录本次失败）
                self._log_call(result, start_time)
                logger.warning(
                    f"[{provider_cfg['name']}]/{model} 失败 → 尝试同平台下一个模型"
                )

            # L3: 下一个供应商
            logger.warning(
                f"供应商 [{provider_cfg['name']}] 全部失败 → 尝试下一个供应商"
            )

        # L4: 优雅降级
        result = self._graceful_degradation(cache_key)
        self._log_call(result, start_time)
        return result

    def _retry_with_backoff(
        self, provider: dict, model: str, system_prompt: str, user_prompt: str
    ) -> ModelResult:
        """L1: 指数退避重试"""
        last_error = None
        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                delay = self.retry_base_delay * (2 ** (attempt - 1))
                logger.warning(
                    f"[{provider['name']}]/{model} 第 {attempt}/{self.max_retries} 次重试，等待 {delay:.1f}s"
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
                if not result.retryable:
                    logger.warning(
                        f"[{provider['name']}]/{model} 错误不可重试，跳过该模型"
                    )
                    return result
                last_error = result.error
            except Exception as e:  # noqa: BLE001
                last_error = str(e)
                logger.warning(
                    f"[{provider['name']}]/{model} 未捕获异常 | 类型={type(e).__name__} | 详情={e}"
                )

        logger.error(
            f"[{provider['name']}]/{model} 全部 {self.max_retries + 1} 次尝试均失败"
            f" | 最后错误={last_error}"
        )
        return ModelResult(
            success=False,
            provider=provider["name"],
            model=model,
            error=last_error or "未知错误",
        )

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
                )

            # 非 200 响应
            status_desc = _describe_http_status(resp.status_code)
            body_preview = resp.text[:200].replace("\n", " ")
            logger.warning(
                f"{label} [HTTP {resp.status_code}] {status_desc}"
                f" | 响应体={body_preview}"
            )

            # 尊重 Retry-After
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    wait = int(retry_after)
                    logger.info(f"{label} 服务端要求等待 {wait}s (Retry-After)")
                    time.sleep(wait)
                except ValueError:
                    pass

            retryable = resp.status_code not in (400, 401, 403, 404)
            return ModelResult(
                success=False,
                provider=provider["name"],
                model=model,
                error=f"HTTP {resp.status_code} ({status_desc}): {body_preview}",
                retryable=retryable,
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
            )

    def _update_cache(self, key: str, result: ModelResult):
        self._cache[key] = (datetime.now(CHINA_TZ), result)

    def _graceful_degradation(self, cache_key: str) -> ModelResult:
        """L4: 优雅降级"""
        if cache_key in self._cache:
            cached_time, cached_result = self._cache[cache_key]
            if datetime.now(CHINA_TZ) - cached_time < self.cache_ttl:
                age = (datetime.now(CHINA_TZ) - cached_time).total_seconds()
                logger.warning(
                    f"[L4] 所有模型均不可用，返回缓存结果"
                    f" | 缓存年龄={age:.0f}s"
                    f" | 原始来源={cached_result.provider}/{cached_result.model}"
                )
                cached_result.from_cache = True
                return cached_result

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
        try:
            self._stats_mapper.insert_log(
                provider_name=result.provider or "unknown",
                model_name=result.model or "unknown",
                call_time=datetime.now(CHINA_TZ),
                success=result.success,
                latency_ms=latency_ms,
                error_reason=result.error[:200] if result.error else None,
                from_cache=result.from_cache,
                triggered_alerts=None,
            )
        except sqlite3.Error:
            logger.warning("AI 调用统计写入失败！")
