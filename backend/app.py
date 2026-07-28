from fastapi import FastAPI

from controller.model_pool_controller import router as model_pool_router
from controller.price_history_controller import router as price_history_router

app = FastAPI(
    title="黄金价格智能监控系统",
    version="1.0.0",
    description="实时监控黄金价格，AI 智能分析，模型池配置管理",
)

app.include_router(model_pool_router, prefix="/api")
app.include_router(price_history_router, prefix="/api")


@app.get("/health", tags=["系统"])
def health_check():
    return {"status": "ok", "service": "黄金价格智能监控系统"}
