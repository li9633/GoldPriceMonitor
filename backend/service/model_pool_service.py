from mapper.model_pool_mapper import ModelPoolMapper
from models.model_pool import (
    ModelProviderCreate,
    ModelProviderResponse,
    ModelProviderUpdate,
    ModelProviderWithModels,
    ProviderModelCreate,
    ProviderModelResponse,
    ProviderModelUpdate,
)
from utils.logger import get_logger

logger = get_logger("ModelPoolService")


class ModelPoolService:
    """模型池配置管理服务 — 业务逻辑 + mapper → Pydantic 转换"""

    def __init__(self) -> None:
        self.mapper = ModelPoolMapper()
        self.mapper.init_tables()

    # ==================== 供应商 ====================

    @staticmethod
    def _mask_api_key(key: str) -> str:
        """脱敏：已设置则显示 ****，未设置则显示提示"""
        return "****" if key else "未设置"

    def list_providers(self) -> list[ModelProviderWithModels]:
        rows = self.mapper.get_providers()
        result: list[ModelProviderWithModels] = []
        for r in rows:
            r["api_key"] = self._mask_api_key(r["api_key"])
            result.append(ModelProviderWithModels(**r))
        return result

    def get_provider(self, name: str) -> ModelProviderWithModels | None:
        row = self.mapper.get_provider_by_name(name)
        if not row:
            return None
        row["api_key"] = self._mask_api_key(row["api_key"])
        return ModelProviderWithModels(**row)

    def create_provider(self, data: ModelProviderCreate) -> ModelProviderResponse:
        self.mapper.insert_provider(
            name=data.name,
            api_url=data.api_url,
            api_key=data.api_key,
            timeout=data.timeout,
            sort_order=data.sort_order,
        )
        logger.info(f"供应商 [{data.name}] 已创建")
        return ModelProviderResponse(
            id=0,
            name=data.name,
            api_url=data.api_url,
            api_key=data.api_key,
            timeout=data.timeout,
            sort_order=data.sort_order,
        )

    def update_provider(self, name: str, data: ModelProviderUpdate) -> bool:
        updates = {
            k: v for k, v in data.model_dump(exclude_none=True).items() if v is not None
        }
        if not updates:
            return False
        result = self.mapper.update_provider(name, **updates)
        if result:
            logger.info(f"供应商 [{name}] 已更新")
        return result

    def delete_provider(self, name: str) -> bool:
        result = self.mapper.delete_provider(name)
        if result:
            logger.info(f"供应商 [{name}] 及其模型已删除")
        return result

    # ==================== 模型 ====================

    def list_models(self, provider_name: str) -> list[ProviderModelResponse]:
        rows = self.mapper.get_models_by_provider(provider_name)
        return [ProviderModelResponse(**r) for r in rows]

    def create_model(
        self, provider_name: str, data: ProviderModelCreate
    ) -> ProviderModelResponse:
        self.mapper.insert_model(
            provider_name=provider_name,
            model_name=data.model_name,
            sort_order=data.sort_order,
        )
        logger.info(f"模型 [{data.model_name}] 已添加到供应商 [{provider_name}]")
        return ProviderModelResponse(
            id=0,
            provider_name=provider_name,
            model_name=data.model_name,
            sort_order=data.sort_order,
        )

    def update_model(self, model_id: int, data: ProviderModelUpdate) -> bool:
        updates = {
            k: v for k, v in data.model_dump(exclude_none=True).items() if v is not None
        }
        if not updates:
            return False
        return self.mapper.update_model(model_id, **updates)

    def delete_model(self, model_id: int) -> bool:
        return self.mapper.delete_model(model_id)
