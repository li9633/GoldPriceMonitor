from fastapi import APIRouter, HTTPException

from models.model_pricing import (
    ModelPricingCreate,
    ModelPricingResponse,
    ModelPricingUpdate,
)
from models.response import ApiResponse
from service.model_pricing_service import ModelPricingService

router = APIRouter(prefix="/pricing", tags=["模型定价"])
service = ModelPricingService()


@router.get("", response_model=ApiResponse[list[ModelPricingResponse]])
def list_pricing():
    return ApiResponse.ok(service.list_all())


@router.put(
    "/{provider_name}/{model_name}", response_model=ApiResponse[ModelPricingResponse]
)
def upsert_pricing(provider_name: str, model_name: str, data: ModelPricingCreate):
    data.provider_name = provider_name
    data.model_name = model_name
    return ApiResponse.ok(service.upsert(data), message="定价已保存")


@router.patch("/{pricing_id}", response_model=ApiResponse[bool])
def update_pricing(pricing_id: int, data: ModelPricingUpdate):
    if not service.update(pricing_id, data):
        raise HTTPException(status_code=404, detail="定价记录不存在")
    return ApiResponse.ok(True, message="已更新")


@router.delete("/{pricing_id}", response_model=ApiResponse[bool])
def delete_pricing(pricing_id: int):
    if not service.delete(pricing_id):
        raise HTTPException(status_code=404, detail="定价记录不存在")
    return ApiResponse.ok(True, message="已删除")
