from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from controller.advice_controller import router as advice_router
from controller.ai_stats_controller import router as ai_stats_router
from controller.exchange_rate_controller import router as exchange_rate_router
from controller.log_controller import router as log_router
from controller.model_pool_controller import router as model_pool_router
from controller.model_pricing_controller import router as pricing_router
from controller.notification_stats_controller import router as notification_stats_router
from controller.portfolio_controller import router as portfolio_router
from controller.price_history_controller import router as price_history_router
from controller.runtime_status_controller import router as runtime_status_router
from controller.system_settings_controller import router as settings_router
from utils.date_filter import InvalidDateError

app = FastAPI(
    title="黄金价格智能监控系统",
    version="1.0.0",
    description="实时监控黄金价格，AI 智能分析，模型池配置管理",
)

app.include_router(advice_router, prefix="/api")
app.include_router(ai_stats_router, prefix="/api")
app.include_router(exchange_rate_router, prefix="/api")
app.include_router(log_router, prefix="/api")
app.include_router(model_pool_router, prefix="/api")
app.include_router(notification_stats_router, prefix="/api")
app.include_router(portfolio_router, prefix="/api")
app.include_router(pricing_router, prefix="/api")
app.include_router(price_history_router, prefix="/api")
app.include_router(runtime_status_router, prefix="/api")
app.include_router(settings_router, prefix="/api")

DIST_DIR = (Path(__file__).resolve().parent.parent / "frontend" / "dist").resolve()


@app.exception_handler(InvalidDateError)
def handle_invalid_date(_request: Request, exc: InvalidDateError) -> JSONResponse:
    """日期参数非法 → 400，不要让它冒泡成 500"""
    return JSONResponse(
        status_code=400, content={"code": 400, "message": str(exc), "data": None}
    )


@app.get("/health", tags=["系统"])
def health_check():
    return {"status": "ok", "service": "黄金价格智能监控系统"}


@app.get("/{full_path:path}")
def serve_spa(full_path: str):
    """前端静态资源 + SPA 兜底路由。

    两处必须防住：

    1. **路径穿越**：`DIST_DIR / full_path` 里带 `..` 时，规范化后会跑到 dist
       之外。原先直接 `FileResponse` 会让 `../../backend/data/prices.db`
       这类请求把整个数据库（含加密的 API Key）或任意源码文件吐出去。
       现在一律 `resolve()` 后用 `is_relative_to` 校验必须落在 dist 之内。
    2. **API 404 被吞**：`/{full_path:path}` 会兜住所有路径，导致打错的
       `/api/xxx` 返回首页 HTML，或者因 `frontend/dist` 不存在而直接 500。
       现在 `/api` 前缀一律 404，dist 缺失时给出明确提示。
    """
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="接口不存在")

    if full_path:
        candidate = (DIST_DIR / full_path).resolve()
        if candidate.is_relative_to(DIST_DIR) and candidate.is_file():
            return FileResponse(candidate)

    index = DIST_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(
            status_code=404,
            detail="前端静态资源未构建（frontend/dist 不存在），请先执行 npm run build",
        )
    return FileResponse(index)
