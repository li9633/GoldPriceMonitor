from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from controller.ai_stats_controller import router as ai_stats_router
from controller.log_controller import router as log_router
from controller.model_pool_controller import router as model_pool_router
from controller.model_pricing_controller import router as pricing_router
from controller.notification_stats_controller import router as notification_stats_router
from controller.price_history_controller import router as price_history_router
from controller.system_settings_controller import router as settings_router

app = FastAPI(
    title="黄金价格智能监控系统",
    version="1.0.0",
    description="实时监控黄金价格，AI 智能分析，模型池配置管理",
)

app.include_router(ai_stats_router, prefix="/api")
app.include_router(log_router, prefix="/api")
app.include_router(model_pool_router, prefix="/api")
app.include_router(notification_stats_router, prefix="/api")
app.include_router(pricing_router, prefix="/api")
app.include_router(price_history_router, prefix="/api")
app.include_router(settings_router, prefix="/api")

DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@app.get("/health", tags=["系统"])
def health_check():
    return {"status": "ok", "service": "黄金价格智能监控系统"}


@app.get("/{full_path:path}")
def serve_spa(full_path: str):
    file_path = DIST_DIR / full_path
    if file_path.is_file():
        return FileResponse(file_path)
    return FileResponse(DIST_DIR / "index.html")
