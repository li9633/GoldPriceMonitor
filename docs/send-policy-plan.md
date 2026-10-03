# 智能消息发送策略 — 市场时段感知方案（草案）

> 状态：**阶段 0.5 已实现**（2026-10-03），代码与测试已落地
> 记录日期：2026-10-03
> 配套文档：[黄金购买建议系统重构方案](./refactor-plan.md)
>
> 文中路径均相对仓库根目录。带 `:行号` 的位置为调研时实测确认。

---

## 0. 一句话

把「用 60 分钟 AI 缓存抑制消息」换成「**按市场时段决定发不发，休市就闭嘴且不花 AI 的钱**」。

---

## 1. 背景：缓存的原始意图

`ModelPool` 的缓存按 `cache_key=symbol` 存储，TTL `ai_config.cache_ttl_minutes`（默认 60 分钟），调用点见 `backend/service/ai_service.py:96`。

它的设计意图是：**周末/节假日上海黄金交易所休市期间，避免重复调用 AI 导致消息轰炸。**

**这个意图是对的，但实现方式是错的。** 具体有两层问题。

---

## 2. 为什么缓存防不住轰炸

### 2.1 缓存返回的是同一个「是/否」，而不是「别发了」

- 缓存命中时返回的是**同一个** `should_alert` 值；
- 而发送判断**只看这个布尔**（`backend/service/monitor_service.py:171` `if not ai_result.get("should_alert"): return`）；
- 所以在 `_periodic_ai_check`（每 5 分钟一次）里，如果 AI 在休市期间说过一次"该通知"，缓存会在 60 分钟内**每次都返回同样的 `true`**。

**结果：缓存不但没有抑制发送，反而保证了同样的判断被重复执行 —— 每 5 分钟照发一次。**

### 2.2 真正能抑制发送的代码从未被调用

`MonitorService._is_in_cooldown()`（`backend/service/monitor_service.py:206-210`，5 分钟冷却）**定义了但没有任何调用点**。

### 2.3 缓存还污染了分析口径

缓存命中时会给分析打上前缀「`[缓存结果，AI 实时分析暂不可用]`」（`backend/service/ai_service.py:114-117`），把「节流」伪装成「分析降级」，让用户以为模型挂了。

### 2.4 结论

缓存承担了它做不到的职责。**必须解耦。**

---

## 3. 三件事必须拆开

| 关注点 | 现状 | 应该由谁负责 |
|---|---|---|
| **AI 调用预算**（省钱） | 缓存 TTL 60min | 缓存 ✅ 本职 |
| **通知抑制**（防轰炸） | 缓存 ❌ **无效** | **独立的发送闸门 `SendPolicyGate`** |
| **分析口径**（看哪个市场） | prompt 里一句话 | **`MarketSession`** |

---

## 4. 已有但未接线的基础

`backend/utils/trading_utils.py` 里**已经实现了**市场时段判断：

| 函数 | 位置 | 能力 |
|---|---|---|
| `_get_trading_hours()` | `:6-19` | 从 `monitor_config.trading_hours` 读取时段，带默认值 |
| `is_autd_trading()` | `:22-48` | 周末 / 法定节假日 / 调休 / 夜盘跨日 |
| `get_trading_status_text()` | `:51-63` | 返回中文状态描述 |

**但它的唯一消费者是 `get_trading_status_text()`，而后者只被用在 `backend/service/ai_service.py:152` —— 往 prompt 里塞一句文本。它从来没有决定过发不发。**

更关键的是，`get_trading_status_text()` 的三条文案**已经就是我们要的策略**：

```
交易时段     → 「Au(T+D) 当前处于交易时段，价格实时更新」
周末         → 「周末休市，伦敦金同样休市，价格均为上一个交易日收盘价，无需过度关注」
节假日/非交易时段 → 「法定节假日休市 / 处于休市时段，伦敦金正常交易，请以伦敦金走势为主要参考」
```

作者已经想清楚了，只是没接到闸门上。

---

## 5. 实测：当闸门用之前必须先修这 3 个边界

按真实场景实跑 `is_autd_trading()`（`chinese_calendar` 已是现有依赖）：

| 场景 | 当前返回 | 实际应为 |
|---|---|---|
| 周日 2025-09-28 10:00（**调休上班**） | **True**「交易时段」❌ | 休市 |
| 周六 2025-09-27 01:00（周五夜盘尾） | False「周末休市，伦敦金同样休市」❌ | SGE 交易中 + **国际金也在交易** |
| 周一 2025-09-29 01:00 | True「交易时段」⚠️ | 需核实（周日晚无夜盘） |
| 周三 2025-10-01 10:00（国庆） | False ✅ | 休市，国际金正常 ✅ |
| 周五 2025-09-26 21:00（夜盘） | True ✅ | 交易中 ✅ |

### 5.1 根因一：调休判反了

实测 `chinese_calendar.is_workday()` 对**调休上班的周末**返回 `True`：

```
2024-10-12 Sat  is_workday=True   is_holiday=False
2024-02-04 Sun  is_workday=True   is_holiday=False
2025-09-28 Sun  is_workday=True   is_holiday=False
2025-10-11 Sat  is_workday=True   is_holiday=False
2025-10-01 Wed  is_workday=False  is_holiday=True
2025-09-27 Sat  is_workday=False  is_holiday=True
```

但 **SGE 周末从不开市**（调休只影响上班，不影响交易所）。所以周日 10:00 被判成「交易时段」。

**修法**：用 `is_holiday(d)` 而不是 `not is_workday(d)`，并且显式要求 `weekday() < 5`。

### 5.2 根因二：夜盘归属错了

`00:00–02:30` 这个窗口属于**前一个交易日**，而现在的代码用**当天**的 `is_workday()` 判断（`backend/utils/trading_utils.py:27-35`），导致两个方向都错：

- 周六 01:00 被判休市（周五夜盘实际延续到 02:30）
- 周一 01:00 被判交易（周日晚无夜盘）

**修法**：早盘窗口用「**前一个自然日**是否交易日 + 是否有夜盘」来判定，而不是当天。

### 5.3 根因三：国际金口径太粗

现在只有「周末休市 / 其他正常」。实际是：

| | 北京时间 |
|---|---|
| 国际金周五收盘 | 周六 **05:00**（夏令时）/ **06:00**（冬令时） |
| 国际金周日开盘 | 周一 **06:00**（夏令时）/ **07:00**（冬令时） |

所以：

- **周六 00:00–05:00**：国际金**还在交易**（对应纽约周五下午），代码却说「伦敦金同样休市」❌
- **周一 00:00–02:30**：国际金**已休市**（周日纽约尚未开盘），代码却说「交易时段」❌

**修法**：国际金用「周几 + 宽松边界」判断，**不要写死精确时间点**，避开夏令时那 1 小时误差。

### 5.4 未覆盖项

国际金假日（圣诞、元旦、感恩节半日市）目前完全没有考虑。**建议 MVP 先不接**（一年就几天），先把周末边界做对。

---

## 6. 目标设计

### 6.1 模块

```python
# backend/utils/market_session.py
class Session(Enum):     OPEN / CLOSED / WEEKEND / HOLIDAY
class SendPolicy(Enum):  NORMAL / INTL_ONLY / LOW_FREQ / SILENT

def sge_session(at: datetime) -> Session     # 修掉 §5.1 §5.2
def intl_session(at: datetime) -> Session    # 修掉 §5.3
def send_policy(at: datetime) -> SendPolicy  # 下面这张矩阵
```

### 6.2 策略矩阵（2×2）

| SGE | 国际金 | 策略 | 说明 |
|---|---|---|---|
| 开市 | 开市 | **NORMAL** | 价格驱动 + 定时巡检，按阈值推 |
| 休市（节假日 / 非交易时段） | **开市** | **INTL_ONLY** | **照常发**，分析主体切到国际金（¥/克 折算） |
| 休市（**周末**） | **休市** | **SILENT** | **且不调 AI** |
| 开市（夜盘尾 / 周一凌晨） | 可能休市 | **LOW_FREQ** | 仅高优先级 |

### 6.3 关键：`SILENT` 必须在调用 AI **之前**短路

```
_tick()
  ├─ 抓价、存库                         （照常）
  ├─ policy = send_policy(now())
  ├─ if policy is SILENT: return        ← 在这里返回：既不发送，也不花 AI 的钱
  ├─ 价格/计划触发器 → 信号
  ├─ 去重闸（§6.4）
  ├─ AI 分析（INTL_ONLY 时口径切国际金）
  └─ 发送 + 落 advice_records
```

这正好是原本想用缓存达到的目的，但由正确的机制来做。

### 6.4 第二道闸：真正的去重（与时段无关）

同一 `action` 且关键指标变化 < 阈值 → 不发。

这是缓存不该管、也管不了的事。建议把 `_is_in_cooldown` 接上或删掉（`backend/service/monitor_service.py:206-210`）。

### 6.5 记录抑制原因

被抑制时在 `advice_records.suppressed_reason` 落库：`silent` / `duplicate` / `low_priority`。

**调策略时这个数据比日志有用得多** —— 以后能回看「当时为什么没发」。这也顺带修好了「`alert_level` 恒为 warning、`urgency` 算完就丢」的问题（`backend/service/monitor_service.py:147`、`:177`）。

---

## 7. 实施记录（已完成）

位置：总体重构计划的**阶段 0.5**（阶段 0 之后、阶段 1 持仓域之前）。不依赖持仓域。

### 7.1 步骤完成情况

| # | 步骤 | 状态 |
|---|---|---|
| 1 | 修 `is_autd_trading()` 的 §5.1 §5.2 两个 bug | ✅ 逻辑迁到 `utils/market_session.py`，`trading_utils` 改为薄封装 |
| 2 | 新增 `intl_session()`（§5.3） | ✅ 按「星期 + 宽松边界」判断 |
| 3 | 新增 `send_policy()` 矩阵 | ✅ `market_session.policy_for()` |
| 4 | 新增发送闸门，在两个下游入口短路 | ✅ `service/send_gate.py`，`MonitorService._tick()` 每周期只判定一次 |
| 5 | 加真正的去重，并把 `_is_in_cooldown` 接上或删掉 | ✅ 新增 `SendDeduplicator`；`_is_in_cooldown` 已删除 |
| 6 | 缓存退回本职 | ✅ 缓存键改为按 prompt 输入分桶；**TTL 未改**（见 §7.4） |

### 7.2 改动清单

**新增**

| 文件 | 作用 |
|---|---|
| `backend/utils/market_session.py` | `Session` / `SendPolicy` 枚举、`is_trading_day`、`sge_session`、`intl_session`、`policy_for`、`send_policy`、`describe` |
| `backend/service/send_gate.py` | `SendGate`、`GateDecision`、`SendDecision`、`SendDeduplicator`、`alert_dedup_key` |
| `backend/test/test_market_session.py` | 15 个用例：日历前置、SGE 时段、国际金、策略矩阵、闸门、去重 |
| `backend/test/test_monitor_send_gate.py` | 10 个用例：`MonitorService` 接线（静默、urgency 映射、去重、回退行为） |

**修改**

| 文件 | 改动 |
|---|---|
| `backend/utils/trading_utils.py` | 判断逻辑改为委托 `market_session`；`get_trading_status_text()` 重写为按两个市场输出 |
| `backend/service/monitor_service.py` | 接入 `SendGate`；`urgency` 映射到 `alert_level`；删掉从未调用的 `_is_in_cooldown`；新增抑制日志 |
| `backend/service/ai_service.py` | 缓存键 `symbol` → `symbol + 三个价格分桶` |

### 7.3 前后判定对比（实测）

| 场景 | 时间 | 旧：SGE 开市 | 新：SGE | 新：国际金 | 新策略 | |
|---|---|---|---|---|---|---|
| 周三 日盘 | 2025-09-24 10:00 | True | open | open | normal | |
| 周三 午休 | 2025-09-24 12:00 | False | closed | open | intl_only | |
| 周五 夜盘 | 2025-09-26 21:00 | True | open | open | normal | |
| 周六 凌晨（周五夜盘尾） | 2025-09-27 01:00 | False | open | open | normal | **改变** |
| 周六 上午 | 2025-09-27 10:00 | False | weekend | weekend | silent | |
| 周日（调休上班） | 2025-09-28 10:00 | True | weekend | weekend | silent | **改变** |
| 周一 凌晨 | 2025-09-29 01:00 | True | closed | weekend | silent | **改变** |
| 周一 日盘 | 2025-09-29 10:00 | True | open | open | normal | |
| 国庆 上午 | 2025-10-01 10:00 | False | holiday | open | intl_only | |
| 周六（调休上班） | 2025-10-11 10:00 | True | weekend | weekend | silent | **改变** |

10 个场景中 **4 个判定改变**，全部是 §5 预测的边界：

- 2 个「旧=开市 / 新=休市」：调休周末 —— 旧逻辑会误发，新逻辑静默；
- 1 个「旧=开市 / 新=休市」：周一凌晨 —— 周日晚无夜盘；
- 1 个「旧=休市 / 新=开市」：周六凌晨 —— 周五夜盘尚未结束，旧逻辑漏发。

### 7.4 实现时确定的设计决策

| 决策 | 取值 | 理由 |
|---|---|---|
| 国际金边界 | 收盘取**较早**的 05:00、开盘取**较晚**的 07:00 | 贯彻「不确定时判为休市」，避开夏令时 1 小时误差 |
| 去重参数 | 冷却 10 分钟 / 价格变动 0.3% | 沿用 `alert_service.py:17-18` 已有的约定 |
| `alert_level` | `high→critical`、`medium→warning`、`low→info` | 前端 `NotificationLogTable.vue:14-16` 已按 `critical`/`warning` 上色，顺势让 `urgency` 不再丢失 |
| 缓存键价格分桶 | 对数分桶，步长 0.3%（`AIAnalysisService._CACHE_PRICE_STEP`） | 休市价格停滞时天然命中；行情明显变动时重新分析 |
| 缓存 TTL | **保持 60 分钟不变** | 见下方成本说明 |

**关于 AI 调用成本（需要留意）**：缓存键改动后，命中条件从「同一小时内」变成「同一小时内且价格未离开同一分桶」。

- 收益：周末与节假日现在**完全不调用 AI**（原先每 5 分钟一次）；
- 代价：活跃交易日可能从约 24 次/天升到约 1–3 倍（取决于当天价格是否跨桶）；
- 旋钮：调大 `AIAnalysisService._CACHE_PRICE_STEP` 可减少调用，调小则更灵敏。

### 7.5 实现时发现的新风险

**`chinese-calendar` 只覆盖 2004–2026**（实测 1.11.0：`is_holiday(2027-01-01)` 抛
`NotImplementedError`）。今天已是 2026-10-03，**约 3 个月后**这个调用就会开始失败。

原先它只影响 prompt 里的一句文本（异常被 `ai_service.analyze` 的 `except` 吞掉，静默
降级）；但一旦用来**决定发不发消息**，未处理的异常就会打断发送链路。

已处理：`market_session._holiday_flag()` 捕获 `NotImplementedError`，降级为「仅按星期
判断」并打一条告警，不会中断发送。

**待办**：升级 `chinese-calendar` 依赖（或在 2026 年底前换用带年份数据的节假日源）。

### 7.6 验证方式

```bash
cd backend
python -m test.test_market_session      # 15 项
python -m test.test_monitor_send_gate   # 10 项
python -m test.test_sqlite_connections  # 3 项（本次未改动，回归确认）
```

另外确认整个 FastAPI app 仍可导入（45 条 API 路径齐全）。
实测运行当天（2026-10-03，周六且国庆假期）策略为 `SILENT`，即系统当天不会推送、
也不会调用 AI。

---

## 8. 待决问题

### 8.1 仍需确认

1. **夜盘 `00:00–02:30` 的归属（唯一的实质风险）**：本文判断「周六凌晨算周五夜盘
   延续、周一凌晨无夜盘」，代码已按此实现并通过测试。但这是交易所日历问题，
   **需要 SGE 的准确规则确认**。
   - 若判断正确 → 周一凌晨为 `SILENT`（当前行为）；
   - 若 SGE 周一凌晨实际开市 → 该时段会变成 `LOW_FREQ`（见 8.2 第 3 条）。

   两种情况下 `policy_for()` 都能给出正确策略，区别只在 `trading_windows()` 里窗口的
   归属写法，因此这条确认不会导致返工，只影响一个 2.5 小时窗口的判定。
2. **国际金假日**：圣诞 / 元旦 / 感恩节半日市暂未覆盖，当前按「周二至周五全天开市」
   处理。建议维持不做（一年仅数日），但需知晓这几天可能多推几条。

### 8.2 已在本轮确定

3. **`LOW_FREQ` 的高优先级定义**：实现为「仅放行 `urgency == "high"`」。
   实测发现一个简化：按当前规则 **`LOW_FREQ` 实际不可达** —— 国际金只在周末固定休市，
   而 SGE 在周末同样休市，所以矩阵只会命中 `NORMAL` / `INTL_ONLY` / `SILENT` 三态。
   保留它是作为兜底：一旦 §8.1 第 1 条被推翻，或将来接入国际金假日，它就会生效。
4. **抑制原因记录方式**：已实现为日志（同一原因首次记 INFO、重复降为 DEBUG，避免静默期
   刷屏）。落库到 `advice_records.suppressed_reason` 需要等阶段 2 建表。
5. **缓存 TTL**：保持 60 分钟不变，只改键。成本影响与调节旋钮见 §7.4。
