"""购买建议接口。

注意路由声明顺序：`/now`、`/history`、`/reviews/*` 必须排在 `/{advice_id}` **之前**，
否则 `/{advice_id}` 会先把它们吃掉（路径参数是 int，解析失败会直接 422）。
"""

from fastapi import APIRouter, Query

from models.advice import AdviceNowResponse, AdviceRecord, AdviceReviewStats
from models.response import ApiResponse, PageResponse
from service.advice.advice_engine import AdviceEngine

router = APIRouter(prefix="/advice", tags=["购买建议"])

service = AdviceEngine()

_SYMBOL_DESC = "品种代码，默认取主监控品种"


# ==================== 生成与查询（具体路径必须在前） ====================


@router.get("/now", response_model=ApiResponse[AdviceNowResponse])
def get_advice_now(
    symbol: str | None = Query(None, description=_SYMBOL_DESC),
    fast: bool = Query(
        False, description="true 时跳过 AI 措辞，只返回规则结论（更快、不消耗 token）"
    ),
):
    """手动请求一条建议 —— 「现在该不该买」这个入口"""
    try:
        return ApiResponse.ok(service.now(symbol, use_llm=False if fast else None))
    except ValueError as exc:
        return ApiResponse.fail(str(exc), code=404)


@router.get("/entry-strategy", response_model=ApiResponse[dict])
def get_entry_strategy(
    symbol: str | None = Query(None, description=_SYMBOL_DESC),
    lookback_days: int = Query(365, ge=60, le=1095, description="回看天数"),
    horizon_days: int = Query(30, ge=5, le=180, description="评估持有期（天）"),
):
    """建仓方式回测：一次性 vs 分批，用真实历史算出证据。

    回答的是「分批还是一次性」，不涉及具体买多少克。
    """
    target = symbol or service.main_symbol()
    price, _ = service.resolve_price(target)
    if price is None:
        return ApiResponse.fail(f"品种 {target} 没有可用价格，无法回测", code=404)
    result = service.entry_evaluator.evaluate(
        target, price, lookback_days=lookback_days, horizon_days=horizon_days
    )
    return ApiResponse.ok(result.to_dict())


@router.get("/followups/pending", response_model=ApiResponse[list[dict]])
def list_pending_followups():
    """当前到点、但还没生成复盘的「买入 × 档位」"""
    pending = service.pending_reviews()
    return ApiResponse.ok(
        [
            {
                "lot_id": lot.get("id"),
                "symbol": lot.get("symbol"),
                "trade_date": lot.get("trade_date"),
                "grams": lot.get("grams"),
                "price_per_gram": lot.get("price_per_gram"),
                "horizon_days": horizon,
            }
            for lot, horizon in pending
        ]
    )


@router.get("/history", response_model=ApiResponse[PageResponse[AdviceRecord]])
def list_advice_history(
    symbol: str | None = Query(None, description=_SYMBOL_DESC),
    kind: str | None = Query(
        None, description="pre_purchase / post_purchase / plan_execution"
    ),
    status: str | None = Query(
        None, description="delivered / acknowledged / acted / expired / suppressed"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    items = service.history(symbol, kind, status, page_size, (page - 1) * page_size)
    total = service.count(symbol, kind, status)
    return ApiResponse.ok(PageResponse.of(items, total, page, page_size))


@router.post("/reviews/refresh", response_model=ApiResponse[dict])
def refresh_reviews():
    """回填到期的 T+1 / T+7 / T+30 价格（建议有效性追踪）"""
    return ApiResponse.ok(service.refresh_reviews(), message="回访价格已更新")


@router.get("/reviews/stats", response_model=ApiResponse[AdviceReviewStats])
def get_review_stats():
    return ApiResponse.ok(service.review_stats())


# ==================== 单条建议 ====================


@router.get("/{advice_id}", response_model=ApiResponse[AdviceRecord])
def get_advice(advice_id: int):
    record = service.get(advice_id)
    if record is None:
        return ApiResponse.fail(f"建议 {advice_id} 不存在", code=404)
    return ApiResponse.ok(record)


@router.post("/{advice_id}/ack", response_model=ApiResponse[AdviceRecord])
def acknowledge_advice(advice_id: int):
    if not service.mark_acknowledged(advice_id):
        return ApiResponse.fail(f"建议 {advice_id} 不存在", code=404)
    return ApiResponse.ok(service.get(advice_id), message="已标记为已读")


@router.post("/{advice_id}/acted", response_model=ApiResponse[AdviceRecord])
def mark_advice_acted(
    advice_id: int,
    lot_id: int | None = Query(None, description="对应实际成交的买入记录 ID"),
):
    """记录「我照做了」—— 这是评估建议有效性的基础"""
    if not service.mark_acted(advice_id, lot_id):
        return ApiResponse.fail(f"建议 {advice_id} 不存在", code=404)
    return ApiResponse.ok(service.get(advice_id), message="已记录为已执行")
