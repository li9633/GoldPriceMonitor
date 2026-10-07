# 价格获取与通知策略重构方案（草案）

> 状态：**阶段 A、B、C、D 已实现**（2026-10-07）；阶段 E 价格 provider 化待做
> 记录日期：2026-10-07
> 起因：2026-10-01 ~ 10-07 法定节假日，7 天仅收到 1 条推送（见 §1 诊断）
> 配套文档：[智能消息发送策略](./send-policy-plan.md)、[黄金购买建议系统重构方案](./refactor-plan.md)

---

## 0. 一句话

把「所有消息都是建议、所有判断都看 SGE」的旧结构，改成
「**行情上下文按市场切换 + 通知由事件触发器产生 + 渠道只管投递**」。

---

## 1. 诊断：为什么 7 天只收到 1 条

节假日（SGE 休市、国际金开市）走 `INTL_ONLY` 策略，`allowed=True`，
评估循环每 5 分钟照常跑——闸门没拦，但：

1. `AdviceContext.indicators` 全部由 **main_symbol（Au T+D）的冻结序列**构建
   （`monitor_service.py:165-170` 传 `current_price` = SGE 价）；
   伦敦金只作参考字段传入。send-policy-plan §6.2 承诺的
   「INTL_ONLY 分析主体切到国际金」**没有实现位置**。
2. `_should_push()`（`monitor_service.py:331-349`）比较基准也是 SGE 价格：
   动作恒定 + 价格偏离 0% → 每次评估都被抑制为 `duplicate`。
3. 结果：假期国际金动得越凶，用户收到的消息越少——而它恰恰决定节后开盘缺口。

---

## 2. 结构性笨拙点清单（带证据）

| # | 笨拙点 | 证据 | 后果 |
|---|---|---|---|
| 1 | **所有外发消息都是「建议」** | `channels/base.py:1`「所有外发消息都是建议，载荷为 AdviceData」；`AdvicePayload` 塞满 action/price_band/confidence 建议专用字段 | 每日摘要、波动提醒、缺口预告没有合法表达形式，只能伪装成建议 |
| 2 | **「分析哪个市场」没有决策点** | 指标构建隐含绑定 main_symbol；`policy_for()` 只影响发送，不影响输入 | 假期口径切换无处安放（§1 根因） |
| 3 | **两套节流并存** | `_should_push`（DB last_pushed，基准=主品种，`monitor_service.py:331`）+ `SendDeduplicator`（内存 10min/0.3%，`send_gate.py:68-113`） | 语义重叠、参数不同、基准不一致，维护两处 |
| 4 | **触发 = 周期轮询 + 事后抑制** | 大 while 循环里 `_advise` 定时评估，靠闸门拦 | 新增通知类型没有挂载点，只能往 `_tick` 里堆 if |
| 5 | **价格源单一且硬编码** | `config.GOLD_PRICE_API_URL`（新浪），`FIELD_INDEX_MAP` 位置索引解析；而 `providers/` 已有汇率 provider 抽象先例 | 换源/加源要动 PriceService 本体 |
| 6 | **节假日日历年底到期** | `chinese-calendar` 仅覆盖 2004-2026（send-policy-plan §7.5 已记录待办） | 2027-01-01 起节假日判断降级为仅按星期 |

**结论**：这不是在 `_tick` 里加两个 if 能解决的。通知链路的四个环节
（用什么行情、谁触发、怎么节流、怎么投递）需要各自归位。

---

## 3. 目标架构

```
MarketView(symbol)                ← 行情上下文按品种参数化（阶段 B）
      ↓
TriggerRegistry.evaluate(tick)    ← 事件触发器（阶段 C/D）
  ├─ AdviceTrigger       动作变化 / 价格偏离（现有逻辑迁入）
  ├─ FollowupTrigger     T+n 复盘（现有逻辑迁入）
  ├─ VolatilityTrigger   波动事件（新增，节假日主力）
  ├─ DailyDigestTrigger  每日摘要（新增）
  └─ ReopenGapTrigger    节后缺口预告（新增）
      ↓ NotificationEvent(kind, payload, dedup_key, urgency, cooldown)
SendGate                          ← 统一闸门（保留，去重参数由事件声明）
      ↓
NotificationService.dispatch(ev)  ← 按 kind 选模板（阶段 A 泛化）
      ↓
channels（企业微信 / 邮件，只认 NotificationData）
```

核心类型：

```python
@dataclass
class NotificationEvent:
    kind: str                 # advice / review / volatility / digest / reopen_gap
    symbol: str
    payload: dict             # 由模板渲染器消费
    dedup_key: str            # 触发器声明，替代现在两处各自拼 key
    urgency: str              # high / medium / low
    cooldown_minutes: float   # 触发器自己声明冷却
    price_basis: float        # 该事件的价格基准（去重比较用）
```

---

## 4. 各环节设计

### 4.1 行情上下文：`MarketView` 按品种参数化（阶段 B）

- `MarketIndicators.from_snapshot()` 本身已是纯函数（`context.py:47-114`），
  只需把「取哪个品种的 snapshot」参数化：`MarketView(symbol)` 内部封装
  `PriceSnapshot` 构建与指标提取。
- `AdviceContext.indicators` 接收 `MarketView` 的产物，不再隐含 main_symbol。
- **口径切换规则**：`policy == INTL_ONLY` 时，建议上下文用 `hf_XAU` 构建，
  持仓浮盈按国际金折算克价重估（基准差在消息里注明「按国际金折算」）；
  `SILENT` / `LOW_FREQ` 维持现状。
- `_should_push` 的价格基准随上下文走，不再是写死的主品种价格。

### 4.2 触发器框架（阶段 C）

```python
class Trigger(ABC):
    kind: str
    def evaluate(self, tick: TickContext) -> NotificationEvent | None: ...
```

- `TickContext`：本轮价格（双品种）、`GateDecision`、上一条已推送事件。
- `AdviceTrigger` / `FollowupTrigger` 迁移现有逻辑，行为不变；
  **两套节流合并**：`_should_push` 的「动作变化 / 价格偏离」判定并入
  `AdviceTrigger`，`SendDeduplicator` 保留为唯一执行层，
  冷却参数从硬编码改为事件携带。

### 4.3 新增触发器（阶段 D）

| 触发器 | 触发条件 | 内容 | 冷却 |
|---|---|---|---|
| `VolatilityTrigger` | 参考价较基准移动 ≥ 阈值（默认 1%） | 涨跌、折算克价、持仓浮盈影响 | 60 分钟 |
| `DailyDigestTrigger` | 每日固定时间（默认 20:00） | 昨日/假期累计涨跌、现价、持仓变化 | 1 条/天 |
| `ReopenGapTrigger` | SGE 开市前（假日最后交易日 20:00） | 假期累计变动、开盘缺口预期 | 1 条/假期 |

基准选择：`VolatilityTrigger` 基准 = 「上次该触发器通知时的价格」与
「最近一次 SGE 收盘价」取**偏离更大者**（保证长假首日就有感知）。
触发器在 `SILENT` 时段同样被闸门拦截，不特殊化。

### 4.4 通知管道泛化（阶段 A，先行）

- `AdviceData` → `NotificationData(kind, ...)`；`advice` 字段变为可选的
  `advice: AdvicePayload | None`，新增 `digest` / `volatility` 等 payload。
- 模板注册制：`MessageTemplate` 按 kind 注册渲染器，替代全硬编码。
- `notification_send_logs` 兼容：`alert_level` 继续沿用上色约定
  （`critical`/`warning`/`info`），非建议类事件默认 `info`。
- 非建议类事件**不写 `advice_records`**（它只存建议），投递日志
  `notification_send_logs` 已足够审计。

### 4.5 价格层（阶段 E，最小化）

- 对齐 `providers/` 汇率模式：`providers/price/` 目录 + `SinaPriceProvider`
  作为默认实现，`PriceService` 变薄壳。**不引入多源切换**（单用户场景
  收益低），只为换源时不动调用方。
- `chinese-calendar` 换源/升级（2026 年底前必须完成，随本阶段一起）。

---

## 5. 落地路径（每步独立上线）

| 阶段 | 内容 | 交付价值 | 风险 |
|---|---|---|---|
| **A · 通知载荷泛化** | `NotificationData(kind)` + 模板注册制 | 现有行为不变，但「发非建议消息」成为可能 | 低 |
| **B · MarketView 参数化** | 指标/信号可基于任意品种；INTL_ONLY 真正切口径；`_should_push` 基准切换 | **直接修复本次节假日静默** | 中：持仓浮盈口径需确认 |
| **C · 触发器框架** | Trigger 接口 + 迁移现有两类 + 合并两套节流 | 行为不变，结构归位 | 中：回归测试要覆盖 |
| **D · 三个新触发器** | 波动 / 每日摘要 / 节后缺口 | 节假日的完整信息覆盖 | 低 |
| **E · 价格 provider + 日历换源** | 新浪 provider 化；日历 provider 链 | 可换源；日历不失效 | 低。**已展开为独立文档** [infra-refactor-plan.md](./infra-refactor-plan.md)（含模型池限速惩罚，可与阶段 A 并行） |

依赖关系：A → B → C → D；E 独立可并行。
**最小可用组合 = A + B**（解决本次问题），C/D 是把这次借的「if 债」还掉。

---

## 7. 实施记录（阶段 A、B，已完成，2026-10-07）

| 项 | 实现 | 测试 |
|---|---|---|
| 阶段 A | `AdviceData` → `NotificationData(kind)`（保留别名）；`MessageTemplate.format(kind)` 分发 + 通用渲染器（`KIND_TITLES` 登记即用）；`NotificationService.send()` 新入口，非建议类默认 info 级 | `test_notification_payload` 9 项 |
| 阶段 B | `AdviceContext.market_symbol`：主体不变、口径可切；`compute/build_context(market_symbol=…)`；INTL_ONLY 时评估价、节流基准、去重比较全部切国际金折算价；`extra_info.valuation_note` 渲染进两种模板；`evidence.market_view` 追溯 | `test_market_view` 8 项 |

浮盈口径按用户拍板落地：SGE 开市用 SGE 价，否则用国际金折算价，消息注明「可能与国内开盘价存在偏差」。
行为与方案的一处偏差：`NotificationData.alert_level` 默认值保持旧值 `warning`（兼容旧测试契约），
非建议类的 info 降级在 `send()` 分发时做。

### 7.2 实施记录（阶段 C、D，已完成，2026-10-07）

| 项 | 实现 | 测试 |
|---|---|---|
| 阶段 C | `service/triggers/`：Trigger / TickContext / NotificationEvent / TriggerRegistry；AdviceTrigger（评估节流+推送节流迁入）、FollowupTrigger（复盘迁入，`save_suppressed=False` 保留刻意不落库语义）；MonitorService 统一 `_handle_outcome`（闸门→落库→投递）；去重冷却由事件声明 | `test_trigger_framework` 10 项 |
| 阶段 D | VolatilityTrigger（1%/2.5% 两档、双基准、60min 冷却、强提醒不受限）、DailyDigestTrigger（默认 20:00、每天一条、附假期累计与持仓）、ReopenGapTrigger（法定节假日最后一天 20:00、每假期一条）；阈值全部进 advice_config 表（列迁移 `_migrate_advice_config`） | `test_notification_triggers` 13 项 |

三触发器均服从现有静默闸门（SILENT 不发），零流程豁免；波动提醒交易日同样生效（口径随市场走）。

---

## 6. 待决问题

1. **假期浮盈口径**：INTL_ONLY 期间持仓浮盈按国际金折算克价重估（有基差，
   与节后实际成交价可能不一致）还是维持 SGE 冻结价不变、只报行情？
   倾向前者 + 消息中注明。
2. **每日摘要时间**：08:00（看隔夜）还是 20:00（看全天）？
3. **波动阈值**：1% 起步？基准取「上次通知价」还是「节前 SGE 收盘」？
4. **`digest` 类消息是否也要前端展示**（通知日志页已能看，是否够用）？
5. **旧 `AlertService` 残留**：阶段 C 完成后 `alert_service.py` 是否整体删除？
