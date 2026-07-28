from fastapi import APIRouter, HTTPException

from models.model_pool import (
    ModelProviderCreate,
    ModelProviderUpdate,
    ModelProviderWithModels,
    ProviderModelCreate,
    ProviderModelResponse,
    ProviderModelUpdate,
)
from models.response import ApiResponse
from service.model_pool_service import ModelPoolService

router = APIRouter(prefix="/providers", tags=["模型池配置"])
service = ModelPoolService()


# ==================== 供应商 ====================
@router.get("", response_model=ApiResponse[list[ModelProviderWithModels]])
def list_providers():
    return ApiResponse.ok(service.list_providers())


@router.get("/{name}", response_model=ApiResponse[ModelProviderWithModels])
def get_provider(name: str):
    provider = service.get_provider(name)
    if not provider:
        raise HTTPException(status_code=404, detail=f"供应商 [{name}] 不存在")
    return ApiResponse.ok(provider)


@router.post("", response_model=ApiResponse[ModelProviderWithModels], status_code=201)
def create_provider(data: ModelProviderCreate):
    existing = service.get_provider(data.name)
    if existing:
        raise HTTPException(status_code=409, detail=f"供应商 [{data.name}] 已存在")
    service.create_provider(data)
    return ApiResponse.ok(service.get_provider(data.name), message="创建成功")


@router.put("/{name}", response_model=ApiResponse[ModelProviderWithModels])
def update_provider(name: str, data: ModelProviderUpdate):
    provider = service.get_provider(name)
    if not provider:
        raise HTTPException(status_code=404, detail=f"供应商 [{name}] 不存在")
    service.update_provider(name, data)
    return ApiResponse.ok(service.get_provider(name), message="更新成功")


@router.delete("/{name}", response_model=ApiResponse[None])
def delete_provider(name: str):
    if not service.get_provider(name):
        raise HTTPException(status_code=404, detail=f"供应商 [{name}] 不存在")
    service.delete_provider(name)
    return ApiResponse.ok(None, message="删除成功")


# ==================== 模型 ====================


@router.get("/{name}/models", response_model=ApiResponse[list[ProviderModelResponse]])
def list_models(name: str):
    if not service.get_provider(name):
        raise HTTPException(status_code=404, detail=f"供应商 [{name}] 不存在")
    return ApiResponse.ok(service.list_models(name))


@router.post(
    "/{name}/models", response_model=ApiResponse[ProviderModelResponse], status_code=201
)
def create_model(name: str, data: ProviderModelCreate):
    if not service.get_provider(name):
        raise HTTPException(status_code=404, detail=f"供应商 [{name}] 不存在")
    result = service.create_model(name, data)
    return ApiResponse.ok(result, message="创建成功")


@router.put(
    "/{name}/models/{model_id}", response_model=ApiResponse[ProviderModelResponse]
)
def update_model(name: str, model_id: int, data: ProviderModelUpdate):
    if not service.get_provider(name):
        raise HTTPException(status_code=404, detail=f"供应商 [{name}] 不存在")
    if not service.update_model(model_id, data):
        raise HTTPException(status_code=404, detail=f"模型 [{model_id}] 不存在")
    return ApiResponse.ok(None, message="更新成功")


@router.delete("/{name}/models/{model_id}", response_model=ApiResponse[None])
def delete_model(name: str, model_id: int):
    if not service.get_provider(name):
        raise HTTPException(status_code=404, detail=f"供应商 [{name}] 不存在")
    if not service.delete_model(model_id):
        raise HTTPException(status_code=404, detail=f"模型 [{model_id}] 不存在")
    return ApiResponse.ok(None, message="删除成功")
