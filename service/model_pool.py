import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import requests

from config import AI_CONFIG, CHINA_TZ
from utils.logger import get_logger

logger = get_logger("ModelPool")


@dataclass
class ModelResult:
    success: bool
    content: str | None = None
    provider: str | None = None
    model: str | None = None
    from_cache: bool = False
    error: str | None = None


class ModelPool:
    """多级 AI 模型池

    L1: 智能重试（指数退避 + 尊重 Retry-After）
    L2: 同平台模型降级（glm-4.7-flash → glm-4-flash）
    L3: 跨供应商故障转移（智谱 → 硅基流动 → ...）
    L4: 优雅降级（返回缓存 / 标记不可用）
    """

    def __init__(self, providers: list[dict]):
        self.providers = providers
        self.max_retries = AI_CONFIG.get("max_retries", 3)
        self.retry_base_delay = AI_CONFIG.get("retry_base_delay", 1.0)
        self.cache_ttl = timedelta(
            minutes=AI_CONFIG.get("cache_ttl_minutes", 60))
        self._cache: dict[str, tuple[datetime, ModelResult]] = {}

    def call(self, system_prompt: str, user_prompt: str,
             cache_key: str = "default") -> ModelResult:
        """多级调用入口 — 按 L1→L2→L3→L4 依次尝试"""
        for provider_cfg in self.providers:
            if not provider_cfg.get("api_key"):
                logger.debug(f"跳过供应商 [{provider_cfg['name']}]：未配置 API Key")
                continue

            for model in provider_cfg.get("models", []):
                logger.info(f"尝试 [{provider_cfg['name']}]/{model} ...")
                # L1: 智能重试
                result = self._retry_with_backoff(
                    provider_cfg, model, system_prompt, user_prompt)
                if result.success:
                    self._update_cache(cache_key, result)
                    return result
                # L2: 同平台下一个模型
                logger.warning(
                    f"[{provider_cfg['name']}]/{model} 失败 → 尝试同平台下一个模型")

            # L3: 下一个供应商
            logger.warning(
                f"供应商 [{provider_cfg['name']}] 全部失败 → 尝试下一个供应商")

        # L4: 优雅降级
        return self._graceful_degradation(cache_key)

    def _retry_with_backoff(self, provider: dict, model: str,
                            system_prompt: str, user_prompt: str) -> ModelResult:
        """L1: 指数退避重试"""
        last_error = None
        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                delay = self.retry_base_delay * (2 ** (attempt - 1))
                logger.warning(
                    f"[{provider['name']}]/{model} 第 {attempt} 次重试，等待 {delay:.1f}s")
                time.sleep(delay)

            try:
                result = self._call_single(
                    provider, model, system_prompt, user_prompt)
                if result.success:
                    if attempt > 0:
                        logger.info(
                            f"[{provider['name']}]/{model} 第 {attempt} 次重试成功")
                    return result
                last_error = result.error
            except Exception as e:  # noqa: BLE001
                last_error = str(e)
                logger.warning(f"[{provider['name']}]/{model} 异常：{e}")

        return ModelResult(success=False, error=last_error or "未知错误")

    def _call_single(self, provider: dict, model: str,
                     system_prompt: str, user_prompt: str) -> ModelResult:
        """单次 API 调用"""
        headers = {
            "Authorization": f"Bearer {provider['api_key']}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "temperature": AI_CONFIG["temperature"],
            "max_tokens": AI_CONFIG["max_tokens"]
        }

        try:
            resp = requests.post(
                provider["api_url"],
                headers=headers,
                json=payload,
                timeout=provider.get("timeout", 30)
            )

            if resp.status_code == 200:
                data = resp.json()
                if "error" in data:
                    return ModelResult(
                        success=False,
                        error=f"API error: {data['error'].get('message', 'unknown')}"
                    )
                choice = data["choices"][0]
                finish_reason = choice.get("finish_reason", "")
                if finish_reason == "length":
                    logger.warning("AI 响应因长度限制被截断，考虑增大 max_tokens")
                return ModelResult(
                    success=True,
                    content=choice["message"]["content"],
                    provider=provider["name"],
                    model=model
                )

            # 尊重 Retry-After
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    wait = int(retry_after)
                    logger.info(f"服务端要求等待 {wait}s (Retry-After)")
                    time.sleep(wait)
                except ValueError:
                    pass

            return ModelResult(
                success=False,
                error=f"HTTP {resp.status_code}: {resp.text[:200]}"
            )

        except requests.RequestException as e:
            return ModelResult(success=False, error=str(e))

    def _update_cache(self, key: str, result: ModelResult):
        self._cache[key] = (datetime.now(CHINA_TZ), result)

    def _graceful_degradation(self, cache_key: str) -> ModelResult:
        """L4: 优雅降级"""
        if cache_key in self._cache:
            cached_time, cached_result = self._cache[cache_key]
            if datetime.now(CHINA_TZ) - cached_time < self.cache_ttl:
                logger.warning("所有模型均不可用，返回缓存结果")
                cached_result.from_cache = True
                return cached_result

        logger.error("所有模型均不可用且无有效缓存，AI 分析暂不可用")
        return ModelResult(
            success=False,
            error="AI 分析暂不可用：所有模型供应商均调用失败"
        )
