from pydantic import BaseModel, Field


class ModelPricingBase(BaseModel):
    input_price: float = Field(default=0, ge=0, description="输入价格（元/百万Token）")
    output_price: float = Field(default=0, ge=0, description="输出价格（元/百万Token）")
    currency: str = Field(default="CNY", description="货币单位")


class ModelPricingCreate(ModelPricingBase):
    provider_name: str = Field(..., description="供应商名称")
    model_name: str = Field(..., description="模型名称")


class ModelPricingUpdate(BaseModel):
    input_price: float | None = Field(default=None, ge=0)
    output_price: float | None = Field(default=None, ge=0)
    currency: str | None = None


class ModelPricingResponse(ModelPricingBase):
    id: int
    provider_name: str
    model_name: str
    updated_at: str

    model_config = {"from_attributes": True}
