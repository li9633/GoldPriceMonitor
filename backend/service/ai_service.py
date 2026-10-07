import json

from mapper.model_pool_mapper import ModelPoolMapper
from service.model_pool_engine import ModelPool
from service.system_settings_service import SystemSettingsService
from utils.logger import get_logger

logger = get_logger("AIService")


class AIAnalysisService:
    """AI 行情分析服务 — 使用 GLM-4-Flash 模型"""

    def __init__(self):
        self.model_pool: ModelPool | None = None
        self._providers_fingerprint: str = ""

    @property
    def enabled(self) -> bool:
        return self.model_pool is not None

    def _ensure_model_pool(self) -> bool:
        # 统一拦住，让 analyze 与 complete 两个入口都遵守 ai_config.enabled
        if not self._ai_enabled():
            if self.model_pool is not None:
                logger.warning("AI 分析停用（设置中已关闭）")
                self.model_pool = None
            return False

        config_mapper = ModelPoolMapper()
        config_mapper.init_tables()
        providers = config_mapper.get_providers()

        if not providers:
            if self.model_pool is not None:
                logger.warning("AI 分析禁用（模型池配置为空）")
                self.model_pool = None
            return False

        import json

        current = json.dumps(providers, sort_keys=True, default=str)
        if self.model_pool is not None and current == self._providers_fingerprint:
            return True

        self.model_pool = ModelPool(providers)
        self._providers_fingerprint = current
        has_api_key = any(p.get("api_key") for p in providers)
        if has_api_key:
            logger.info(f"AI 模型池就绪 providers={len(providers)}")
        else:
            logger.warning(
                f"AI 模型池已加载 {len(providers)} 个供应商，但均未配置 API Key，AI 分析仍不可用"
            )
        return has_api_key

    @staticmethod
    def _ai_enabled() -> bool:
        """AI 总开关 —— 由设置页的 `ai_config.enabled` 控制"""
        try:
            config = SystemSettingsService().get_ai_config()
        except Exception as exc:  # noqa: BLE001
            logger.error(f"AI 配置读取失败（按启用处理） error={exc}", exc_info=exc)
            return True
        return bool(config.get("enabled", True))

    def complete(self, system_prompt: str, prompt: str, cache_key: str) -> dict | None:
        """通用补全入口 —— 复用模型池的重试、故障转移与缓存。

        不做 JSON 解析，把原始内容交给调用方。建议引擎用它来做「措辞」，
        与行情分析层共用同一套模型池。
        """
        if not self._ensure_model_pool():
            return None
        assert self.model_pool is not None
        try:
            result = self.model_pool.call(system_prompt, prompt, cache_key=cache_key)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"AI 调用失败 error={exc}", exc_info=exc)
            return None
        if not result.success or not result.content:
            logger.error(f"AI 返回不可用 error={result.error}")
            return None
        if result.raw_response:
            self._log_token_usage(result.provider, result.model, result.raw_response)
        return {
            "content": result.content,
            "provider": result.provider,
            "model": result.model,
            "from_cache": result.from_cache,
        }

    @staticmethod
    def _log_token_usage(
        provider: str | None, model: str | None, raw_response: str
    ) -> None:
        try:
            data = json.loads(raw_response)
            usage = data.get("usage", {})
            if usage:
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                total_tokens = usage.get("total_tokens", 0)
                logger.debug(
                    f"[{provider}/{model}] Token 用量："
                    f"prompt={prompt_tokens} completion={completion_tokens} total={total_tokens}"
                )
        except (json.JSONDecodeError, KeyError):
            pass

