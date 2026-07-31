from mapper.model_pricing_mapper import ModelPricingMapper
from models.model_pricing import (
    ModelPricingCreate,
    ModelPricingResponse,
    ModelPricingUpdate,
)
from utils.logger import get_logger

logger = get_logger("ModelPricingService")


class ModelPricingService:
    def __init__(self) -> None:
        self.mapper = ModelPricingMapper()
        self.mapper.init_table()

    def list_all(self) -> list[ModelPricingResponse]:
        return [ModelPricingResponse(**r) for r in self.mapper.list_all()]

    def upsert(self, data: ModelPricingCreate) -> ModelPricingResponse:
        self.mapper.upsert(
            provider_name=data.provider_name,
            model_name=data.model_name,
            input_price=data.input_price,
            output_price=data.output_price,
            currency=data.currency,
        )
        logger.info(f"定价已保存 [{data.provider_name}/{data.model_name}]")
        row = self.mapper.get_by_provider_model(data.provider_name, data.model_name)
        if row is None:
            raise RuntimeError("定价保存后查询失败")
        return ModelPricingResponse(**row)

    def update(self, pricing_id: int, data: ModelPricingUpdate) -> bool:
        updates = {
            k: v for k, v in data.model_dump(exclude_none=True).items() if v is not None
        }
        if not updates:
            return False
        return self.mapper.update(pricing_id, **updates)

    def delete(self, pricing_id: int) -> bool:
        return self.mapper.delete(pricing_id)
