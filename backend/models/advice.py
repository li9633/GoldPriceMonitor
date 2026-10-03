"""建议域的数据模型。

设计原则（见 `docs/refactor-plan.md` §4）：

- **规则出事实，LLM 只出表述**。`Signal` 是确定性规则算出的事实，`AdviceRecord`
  是最终产出；算术（克数、成本、盈亏、比例）全部由代码算好，绝不交给 LLM。
- **建议必须可回溯**。`evidence` 冻结当时的行情快照与持仓，否则事后无法回答
  「当时凭什么这么建议」。
- **建议动作是枚举，不是字符串**，取代原来那个 `should_alert` 布尔。
"""

from enum import Enum

from pydantic import BaseModel, Field


class AdviceKind(str, Enum):
    """建议的语境"""

    PRE_PURCHASE = "pre_purchase"  # 购买前：要不要买、这次买多少
    POST_PURCHASE = "post_purchase"  # 购买后：持有 / 补仓 / 止盈 / 止损
    PLAN_EXECUTION = "plan_execution"  # 计划执行：这一批该不该按计划买
    REVIEW = "review"  # 复盘


class AdviceAction(str, Enum):
    """建议动作 —— 取代 `should_alert` 布尔"""

    BUY_NOW = "BUY_NOW"  # 可以买
    BUY_PARTIAL = "BUY_PARTIAL"  # 分批买（本批买多少见 target_grams）
    WAIT = "WAIT"  # 再等等
    AVOID = "AVOID"  # 不建议买入
    HOLD = "HOLD"  # 持有不动
    ADD = "ADD"  # 补仓
    TAKE_PROFIT = "TAKE_PROFIT"  # 止盈（部分）
    STOP_LOSS = "STOP_LOSS"  # 止损


class AdviceStatus(str, Enum):

    DELIVERED = "delivered"  # 已给出
    ACKNOWLEDGED = "acknowledged"  # 用户已读
    ACTED = "acted"  # 用户照做了（回填 acted_lot_id）
    EXPIRED = "expired"  # 已过期
    SUPPRESSED = "suppressed"  # 被闸门抑制，未送达（见 suppressed_reason）


class SignalCategory(str, Enum):
    MARKET = "market"  # 位置 / 趋势 / 波动
    POSITION = "position"  # 成本、盈亏、仓位
    PLAN = "plan"  # 计划进度与到点


#: 动作 → 紧急度。发送闸门用它做优先级过滤（`LOW_FREQ` 只放行 `high`）。
ACTION_URGENCY: dict[str, str] = {
    AdviceAction.STOP_LOSS.value: "high",
    AdviceAction.TAKE_PROFIT.value: "high",
    AdviceAction.BUY_NOW.value: "medium",
    AdviceAction.BUY_PARTIAL.value: "medium",
    AdviceAction.ADD.value: "medium",
    AdviceAction.AVOID.value: "medium",
    AdviceAction.WAIT.value: "low",
    AdviceAction.HOLD.value: "low",
}

#: 动作 → 通知级别。前端 `NotificationLogTable` 已按 critical / warning 上色。
ACTION_ALERT_LEVEL: dict[str, str] = {
    AdviceAction.STOP_LOSS.value: "critical",
    AdviceAction.BUY_NOW.value: "warning",
    AdviceAction.BUY_PARTIAL.value: "warning",
    AdviceAction.ADD.value: "warning",
    AdviceAction.TAKE_PROFIT.value: "warning",
    AdviceAction.WAIT.value: "info",
    AdviceAction.HOLD.value: "info",
    AdviceAction.AVOID.value: "info",
}


class Signal(BaseModel):
    """一条确定性信号 —— 建议的事实依据"""

    id: str = Field(..., description="信号标识，如 long_term_low_3m")
    category: SignalCategory
    severity: str = Field(
        default="info", description="info / notice / warning / critical"
    )
    summary: str = Field(..., description="人话描述，可直接进模板")
    metrics: dict = Field(default_factory=dict, description="支撑该信号的具体数值")


class AdvicePrefs(BaseModel):
    """建议偏好 —— 没有这些就算不出「这次该买多少克」"""

    total_investable: float = Field(
        default=0.0, ge=0, description="计划用于买金的总资金（0 表示未设置）"
    )
    target_grams: float = Field(
        default=0.0, ge=0, description="目标持仓克数（0 表示未设置）"
    )
    target_position_ratio: float = Field(
        default=0.0, ge=0, le=100, description="目标持仓占总资金比例(%)"
    )
    risk_level: str = Field(
        default="balanced", description="conservative / balanced / aggressive"
    )
    absolute_low_price: float = Field(
        default=0.0,
        ge=0,
        description="绝对低价安全线（沿用原 alert_config.absolute_low_price，0 表示未设置）",
    )
    absolute_alert_enabled: bool = Field(
        default=True,
        description="是否启用绝对低价安全线（沿用原 alert_config.enable_absolute_alert）",
    )
    enable_llm: bool = Field(
        default=True, description="是否让 AI 对规则结论做措辞（失败时自动回退）"
    )


class AdviceDraft(BaseModel):
    """策略产出的草案 —— 还没落库、还没经过 LLM 措辞"""

    kind: AdviceKind
    action: AdviceAction
    symbol: str
    target_grams: float | None = Field(default=None, description="本次建议买入/卖出的克数")
    price_band_low: float | None = Field(default=None, description="建议价位下沿")
    price_band_high: float | None = Field(default=None, description="建议价位上沿")
    confidence: float = Field(default=0.5, ge=0, le=1)
    rationale: str = Field(default="", description="规则生成的理由")
    signals: list[Signal] = Field(default_factory=list)
    evidence: dict = Field(default_factory=dict, description="冻结的行情与持仓快照")


class AdviceRecord(BaseModel):
    """落库后的建议"""

    id: int
    created_at: str
    kind: AdviceKind
    action: AdviceAction
    symbol: str
    target_grams: float | None = None
    price_band_low: float | None = None
    price_band_high: float | None = None
    confidence: float = 0.5
    rationale: str = ""
    signals: list[Signal] = Field(default_factory=list)
    evidence: dict = Field(default_factory=dict)
    model_info: str = ""
    status: AdviceStatus = AdviceStatus.DELIVERED
    suppressed_reason: str = ""
    acted_lot_id: int | None = None
    #: 复盘类建议针对的是哪一笔买入，以及是 T+几 的回访
    subject_lot_id: int | None = None
    review_horizon: int | None = None
    price_at_advice: float | None = None
    price_t1: float | None = None
    price_t7: float | None = None
    price_t30: float | None = None
    reviewed_at: str | None = None


class AdviceNowResponse(BaseModel):
    """`GET /api/advice/now` 的返回体：建议 + 得出它的上下文摘要"""

    advice: AdviceRecord
    symbol: str
    current_price: float
    position: dict = Field(default_factory=dict, description="当前持仓摘要")
    plan_progress: list[dict] = Field(default_factory=list)
    prefs_configured: bool = Field(
        default=False, description="是否已配置总资金/目标克数（决定能否给出具体克数）"
    )


class AdviceReviewStats(BaseModel):
    """建议有效性统计 —— 回答「我的建议准不准」"""

    total: int = 0
    with_t1: int = 0
    with_t7: int = 0
    with_t30: int = 0
    avg_move_t1_pct: float | None = None
    avg_move_t7_pct: float | None = None
    avg_move_t30_pct: float | None = None
