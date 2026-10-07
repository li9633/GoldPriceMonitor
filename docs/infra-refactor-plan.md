# 基础设施重构方案（草案）—— 日历 · 模型池 · 价格源

> 状态：**§1 日历链、§2 模型池惩罚已实现**（2026-10-07，分支 refactor/calendar-provider、refactor/model-pool-penalty）；
> §3 价格 provider 化待做；§4 清理项随本批完成
> 记录日期：2026-10-07
> 配套文档：[价格获取与通知策略重构方案](./notification-refactor-plan.md)（其阶段 E 的展开）
> 原则：**接口 → 实现类**，调用方不关心实现与回退；流程保持不变，行为变化逐条列出（§5）

---

## 1. 节假日日历：provider 链 + 按天缓存

### 1.1 现状

- `market_session._holiday_flag()` 直接 `from chinese_calendar import is_holiday`（`market_session.py:144`），
  超出覆盖年份（1.11.0 为 2004-2026）抛 `NotImplementedError` → 捕获后**降级为仅按星期判断**并告警一次。
- 问题：① 依赖升级不及时 → 2027-01-01 起所有法定节假日判定失效，调休/假日全靠猜；
  ② 降级状态只有一条日志，用户看不见；③ 判断逻辑与具体库耦合，无法替换、无法测试注入。

### 1.2 设计

```python
class CalendarVerdict(Enum):    # KNOWN_HOLIDAY / KNOWN_WORKDAY / UNKNOWN

class TradingCalendarProvider(ABC):
    name: str
    def holiday_info(self, day: date) -> CalendarVerdict: ...

class ChineseCalendarLibProvider    # pip 库：覆盖年份内权威、本地、快
class OnlineCalendarProvider        # 在线 API（如 timor.tech 节假日接口）：库过期后的接棒者
class WeeklyRuleProvider            # 周末=休市兜底：永不失败、永不超范围

class TradingCalendar:              # 门面：回退链 + 缓存 + 观测
    def is_trading_day(self, day: date) -> bool
    @property
    def status(self) -> dict        # 当前生效源 / 是否降级（暴露给 /api/system）
```

- **回退链**：`lib → online → weekly`。调用方（`market_session.is_trading_day`）只认
  `TradingCalendar`，不 import 任何具体源。
- **`UNKNOWN` 贯穿契约**：源答不上来返回 `UNKNOWN` 而不是抛异常/降级日志，
  由门面统一决定回退与告警节奏。
- **按天缓存（关键）**：日历判断每个巡检 tick 都发生。内存缓存当日结果 +
  在线源结果落 SQLite（`system_settings.db` 新表或独立 `calendar_cache` 表）。
  在线源只在缓存 miss 时调用一次/天/年——**热路径零网络**。

### 1.3 相对最初想法的三点强化

| 点 | 理由 |
|---|---|
| 在线源结果**持久化** | 假期判定集中在长假第一天，若恰逢在线源抖动，无缓存则整段长假退化为星期规则 |
| 降级状态进系统 API | 「今天是猜出来的」必须可观测，否则节假日静默会重演且无从排查 |
| `chinese_calendar` 保留为最高优先级 | 本地、权威、零延迟；在线源只接棒过期年份，不替代 |

**待决**：是否引入在线源（新增一个网络依赖）？不引入也成立——链路退化为
`lib → weekly`，配合每年升级提醒；引入则 2027 年无感过渡。倾向引入（缓存兜底后风险很低）。

### 1.4 实施记录（已完成，2026-10-07）与探测结论

探测脚本 `scripts/probe_holiday_apis.py` 实测结论：

- **haoshenqi**：判定方向全部正确（status 0=工作日 / 1=周末 / 2=调休上班 / 3=法定假日），
  2026 覆盖完整 → **选为 OnlineCalendarProvider 实现**；
- timor.tech：不稳定（超时 / 403 反爬）→ 弃用；
- 两个源 2027 均无数据 —— **2027 放假安排本身尚未发布**（预计 2026-11 发布），
  属预期行为，正是回退链存在的意义；
- 已实现：`providers/calendar/{base,chinese_lib,online,weekly,manager}.py` +
  `mapper/calendar_cache_mapper.py`（data/calendar.db，仅在线结果落库、不设过期）；
  `market_session` 改走门面；降级状态经 `GET /api/settings/calendar/status` 暴露；
  测试 `test_calendar_providers` 13 项。

---

## 2. 模型池：限速惩罚 + 跳级调用

### 2.1 现状与证据

调用历史里错误集中在限速类（429 / 账号速率限制 / 模型访问量过大）。当前行为
（`model_pool_engine.py`）：

1. 429 落在 `retryable=True`（`:246` 只排除 400/401/403/404）→ **原地指数退避重试 3 次**
   （1s+2s+4s，`:115-121`），期间还可能全额睡眠服务端 `Retry-After`（`:237-244`，**无封顶**）；
2. 重试耗尽 → 换下一个模型，但**没有任何记忆**：下一次 `call()` 又从第一级模型开始撞 429；
3. `call()` 是同步的，`_tick` 每 10 秒一轮 —— 限速场景下单次调用可阻塞监控循环
   30s~1min（重试睡眠 + Retry-After），且反复烧限速配额。

### 2.2 设计：错误分类 + 双层冷却

```python
class ErrorClass(Enum):
    RATE_LIMITED   # 429 —— 账号级限速（重点）
    OVERLOADED     # 503/504 —— 临时过载
    TRANSIENT      # 超时 / 网络抖动
    FATAL          # 400/401/403/404 / 内容审核 —— 不重试，跳模型

@dataclass
class Cooldown:
    until: datetime
    strikes: int          # 连续触发次数，用于指数升级
```

规则（全部封装在 `ModelPool` 内，`call()` 签名与调用方不变）：

| 事件 | 动作 |
|---|---|
| 某模型 429 | **不原地重试**，直接跳下一级；该模型进入冷却（基准 60s，连续触发 ×2，上限 30min）；同时**供应商级限速计数 +1** |
| 供应商限速计数达到阈值（如 2） | 整个供应商进入较短冷却（基准 120s），**整级跳过** |
| 503/504/超时/网络 | 保留至多 1 次快速重试，失败跳级；模型短冷却 30s |
| `Retry-After` | **封顶 5s**，超过部分折算进冷却时长，不再同步睡眠 |
| 冷却到期 | **恢复正常优先级顺序**（下一轮从 L1 开始）——冷却期内被跳过，到期自动归位 |

### 2.3 相对最初方案的关键补强

1. **限速多半是账号级的，不只是模型级的**：同一 API Key 下 4.7-flash 被 429，
   降到同 Key 的 4-flash 大概率同样 429。所以 429 要**同时记模型级 + 供应商级**两本账，
   否则「跳级」只是把同样的 429 在同账号内再撞一遍。这是原方案最大的漏洞。
2. **惩罚指数升级**：连续 429 说明限速窗口还长，60s → 120s → 240s… 避免每个周期都来探一次。
3. **恢复顺序保留优先级**（原方案已正确）： flap 自限——模型恢复后若立刻又 429，
   会立即重新冷却，最多损失一次尝试。
4. **不持久化冷却状态**：进程重启清零，代价是重启后第一轮可能再撞一次 429，可接受。

### 2.4 顺带修复（同文件，行为不变）

| # | 问题 | 证据 |
|---|---|---|
| 1 | `_log_call` 的延迟统计从**整次 call() 开始**计时，第二、三个模型的日志延迟包含了前面模型的失败耗时 | `model_pool_engine.py:77,92,95` `start_time` 贯穿整个循环 |
| 2 | `_graceful_degradation` 原地修改缓存对象 `cached_result.from_cache = True`，污染缓存 | `:304` |
| 3 | `triggered_alerts` 恒为 `None` | `:330`（refactor-plan §6.1 #9 已记录） |

### 2.5 实施记录（已完成，2026-10-07）

按 §2.2/§2.3 落地：`ErrorClass` 分类、`Cooldown`（模型级 60s 起 ×2 升级封顶 30min；
供应商级 120s 起，2 个模型限速即整级冷却）、Retry-After 睡眠封顶 5s 且折算进冷却、
成功清零该供应商全部冷却、冷却到期自动恢复优先级顺序。
顺带修复 §2.4 的 #1（延迟按模型单独计）与 #2（`replace()` 替代原地改缓存）。
测试 `test_model_pool` 12 项（假件替换 `_call_single`，零网络）。

---

## 3. 价格源 provider 化

对齐 `providers/` 汇率模式（`BaseExchangeRateProvider` + manager）：

```
providers/price/
  base.py            # PriceProvider(ABC) + PriceQuote（统一报价结构）
  sina.py            # SinaPriceProvider（现 huilvbiao 接口 + FIELD_INDEX_MAP 位置解析整体迁入）
```

- `PriceService` 变薄壳：`fetch_all_gold_prices` 委托给注入的 provider。
- **不引入多源切换**：单用户场景收益低；接口化只为换源时不动调用方。
- 行为完全不变（解析逻辑原样搬迁）。

---

## 4. 顺手清理清单（零风险）

| # | 项 | 证据 |
|---|---|---|
| 1 | **`utils/trading_utils.py` 整体删除**：`is_autd_trading` / `get_trading_status_text` 全库零调用方（阶段 2 重写 ai_service 时调用点消失），docstring 引用的调用关系也已过时 | grep 实测仅自身命中 |
| 2 | `ExchangeRateProviderManager`：基类 `is_available()` 从未被 manager 调用 → 删 | `providers/base.py:31` |
| 3 | 汇率**全失败无负缓存**：manager 的缓存只在成功时写入（`providers/__init__.py:67`），全挂时每个调用方都串行打三个源（最长 ~30s/tick）→ 加 60s 失败负缓存 | 见 §5 行为变化 #3 |
| 4 | `notification_send_logs` 建表 DDL 双份 → 收敛（refactor-plan §6.2 #6 已记录） |  |

---

## 5. 行为变化明示（应「保持流程不变」要求的逐条申报）

| # | 变化 | 旧行为 | 新行为 | 影响面 |
|---|---|---|---|---|
| 1 | 429 不再原地重试 | 睡 1+2+4s 后跳级，下轮再撞 | 立即跳级 + 冷却 | 仅失败路径；成功路径不变 |
| 2 | `Retry-After` 睡眠封顶 5s | 全额同步睡眠（可阻塞监控循环 1min+） | 封顶 + 折算进冷却 | 仅失败路径 |
| 3 | 汇率全失败负缓存 60s | 每次调用都串行打三个源 | 60s 内直接用旧缓存兜底 | 仅全部数据源失败时 |
| 4 | 库过期年份的节假日判定 | 星期规则（调休/假日判不准） | 在线源接棒（若引入） | 仅 chinese-calendar 覆盖范围外 |

成功路径、通知触发、建议生成、投递链路的语义一律不变。

---

## 6. 实施顺序建议

挂在 notification-refactor-plan 的阶段线上：

- **模型池惩罚（§2）**：独立、收益立竿见影（调用历史显示限速是最高频错误），可与阶段 A 并行；
- **日历 provider 链（§1）**：对应通知阶段 B 的前置（口径切换依赖 `is_trading_day` 注入），
  且 2026 年底前必须落地在线源决策；
- **价格 provider（§3）+ 清理（§4）**：随时可做，不阻塞任何阶段。
