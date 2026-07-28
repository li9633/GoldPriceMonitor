from pydantic import BaseModel, Field


# ==================== 供应商 ====================
class ModelProviderBase(BaseModel):
    """供应商基础字段"""

    name: str = Field(..., description="供应商名称", examples=["智谱"])
    api_url: str = Field(..., description="API 地址")
    api_key: str = Field(..., description="API Key 对应的环境变量名，如 GLM_API_KEY")
    timeout: int = Field(default=30, ge=1, description="请求超时（秒）")
    sort_order: int = Field(default=0, ge=0, description="排序权重，越小越优先")


class ModelProviderCreate(ModelProviderBase):
    """创建供应商 — POST 请求体"""


class ModelProviderUpdate(BaseModel):
    """更新供应商 — PUT/PATCH 请求体，所有字段可选"""

    name: str | None = Field(default=None, description="供应商名称")
    api_url: str | None = Field(default=None, description="API 地址")
    api_key: str | None = Field(
        default=None, description="API Key 对应的环境变量名，如 GLM_API_KEY"
    )
    timeout: int | None = Field(default=None, ge=1, description="请求超时（秒）")
    sort_order: int | None = Field(default=None, ge=0, description="排序权重")


class ModelProviderResponse(ModelProviderBase):
    """供应商响应 — GET 返回体"""

    id: int = Field(..., description="供应商 ID")

    model_config = {"from_attributes": True}


# ==================== 模型 ====================
class ProviderModelBase(BaseModel):
    """供应商下模型基础字段"""

    provider_name: str = Field(..., description="所属供应商名称")
    model_name: str = Field(..., description="模型名称", examples=["glm-4.7-flash"])
    sort_order: int = Field(default=0, ge=0, description="排序权重，越小越优先")


class ProviderModelCreate(ProviderModelBase):
    """创建模型 — POST 请求体"""


class ProviderModelUpdate(BaseModel):
    """更新模型 — PUT/PATCH 请求体"""

    model_name: str | None = Field(default=None, description="模型名称")
    sort_order: int | None = Field(default=None, ge=0, description="排序权重")


class ProviderModelResponse(ProviderModelBase):
    """模型响应 — GET 返回体"""

    id: int = Field(..., description="模型 ID")

    model_config = {"from_attributes": True}


# ==================== 聚合视图 ====================


class ModelProviderWithModels(ModelProviderResponse):
    """供应商 + 旗下模型列表"""

    models: list[str] = Field(default_factory=list, description="模型名称列表")
