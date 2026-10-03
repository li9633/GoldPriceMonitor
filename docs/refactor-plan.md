# 黄金购买建议系统 — 重构方案（草案）

> 状态：**讨论中，尚未开始实现**
> 记录日期：2026-10-03
> 配套文档：[智能消息发送策略](./send-policy-plan.md)
>
> 文中路径均相对仓库根目录。带 `:行号` 的位置为调研时实测确认。

---

## 0. 一句话

把系统从「**价格越线就通知你**」改成「**结合你的持仓、成本和购买计划，告诉你现在该做什么**」。

---

## 1. 背景与目标

### 1.1 使用场景

黄金行情的**购买建议**，围绕用户的实际购买行为展开：

- 购买**前**：现在该不该买？这次买多少？
- 购买**后**：这笔买得怎么样？接下来持有、补仓还是止盈？
- **买了多少**黄金
- **怎样**购买的（渠道）
- **分批还是一次性**买入
- 结合市场情况，综合给出建议

### 1.2 现状与差距

当前系统的隐含假设是「用户是匿名旁观者，产出是价格越线通知」。证据：

| 差距 | 证据 |
|---|---|
| 建议是**无主体文案** | `AlertService.check_all_conditions()` 返回两个字符串列表（`backend/service/alert_service.py:26`），如「建议：可考虑分批建仓，止损位设在近期低点」 |
| **没有持仓概念** | 全库检索 `portfolio\|position\|holding\|持仓\|成本`：后端 0 命中，前端 0 命中。唯一的"买入"是两句硬编码文案（`alert_service.py:93`、`:268`） |
| **没有用户概念** | `alert_config` 是单行覆盖式配置（`backend/mapper/system_settings_mapper.py:37-58`），`_upsert` 固定写 `id=1`，`_get_row` 只查 `WHERE id=1`（`:323-344`）。用户相关字段只有 `absolute_low_price` |
| 触发是**纯价格驱动** | 单个大循环 `while True: _tick(); sleep(check_interval)`（`backend/service/monitor_service.py:59-68`） |
| 判断权**整体让给 LLM** | 8 个规则算法被注释掉（`backend/service/alert_service.py:38-53`），只剩绝对低价；`should_alert` 由 AI 决定（`backend/service/ai_service.py:239-258`） |

### 1.3 结论

这不是「改造 `alert_service`」，而是**新增一个独立的「持仓 + 建议」域，让它成为首页中心，把现有行情能力降级为它的输入**。

转变会穿透五层：**数据模型 → 建议生成 → 触发模型 → 通知模板 → 前端信息架构**。

---

## 2. 已确认的三个前提

| 决定 | 省掉的 | 保留的 |
|---|---|---|
| **单用户**，先服务作者本人 | `user_id` 贯穿、鉴权、多租户配置 | 沿用 `SystemSettingsService` 单例 + `id=1` 单行配置模式 |
| **手工录入**买入记录 | 银行/券商对账导入、数据清洗、去重 | 录入表单 + CRUD；**必须支持补录历史买入**（用户已有仓位） |
| **统一按「克」** | 份额换算、渠道费率矩阵、回购折价 | `channel` 仅作归档/分组用的字符串；`fee` 保留可空字段 |

**关于 `fee`**：先按「纯克」算，`成本价 = 总金额 / 总克数`；`fee` 只落库、**不摊入成本**。这样以后想按渠道精算不必改表。

---

## 3. 领域模型

### 3.1 为什么新建 `portfolio.db` 而不是并入 `system_settings.db`

`system_settings.db` 里的表是**覆盖式**的（固定 `id=1`）。持仓是**追加式流水**，语义冲突。独立库也便于单独备份。

### 3.2 三张表

```sql
purchase_lots(          -- 买入批次：回答「买了多少、怎么买的」
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol        TEXT    NOT NULL,
  trade_date    TEXT    NOT NULL,           -- YYYY-MM-DD
  grams         REAL    NOT NULL,
  price_per_gram REAL   NOT NULL,
  fee           REAL    DEFAULT 0,          -- 只记录，暂不摊入成本
  channel       TEXT    DEFAULT '',          -- 金店/银行积存金/ETF/纸黄金…
  plan_id       INTEGER NULL,                -- 关联到哪一批计划
  note          TEXT    DEFAULT '',
  created_at    TEXT
)

purchase_plans(         -- 购买计划：回答「分批还是一次性」（事前）
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol        TEXT    NOT NULL,
  target_grams  REAL    NOT NULL,
  budget        REAL    NULL,
  tranches      INTEGER DEFAULT 1,           -- 1 = 一次性
  tranche_grams REAL    NULL,
  trigger_policy TEXT   DEFAULT '{}',        -- JSON: {type:'interval',days:7}
                                             --     | {type:'drop_pct',pct:1.0}
  start_date    TEXT,
  end_date      TEXT    NULL,
  status        TEXT    DEFAULT 'active',    -- active/paused/done/cancelled
  created_at    TEXT,
  updated_at    TEXT
)

advice_records(         -- 建议 + 审计 + 有效性追踪
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at     TEXT,
  kind           TEXT,                       -- pre_purchase/post_purchase/plan_execution/review
  action         TEXT,                       -- 见 §4.2
  symbol         TEXT,
  target_grams   REAL    NULL,
  price_band_low  REAL   NULL,
  price_band_high REAL   NULL,
  confidence     REAL    NULL,
  rationale      TEXT,                       -- LLM 或模板生成的人话
  signals        TEXT,                       -- JSON：命中的确定性信号列表
  evidence       TEXT,                       -- JSON：冻结的 MarketSnapshot + Position
  model_info     TEXT    DEFAULT '',
  status         TEXT    DEFAULT 'delivered',-- delivered/acknowledged/acted/expired/suppressed
  suppressed_reason TEXT DEFAULT '',         -- silent/duplicate/low_priority（见配套文档）
  acted_lot_id   INTEGER NULL,               -- 用户"照做了"→ 回填实际成交
  price_at_advice REAL,                      -- 有效性追踪
  price_t1       REAL    NULL,
  price_t7       REAL    NULL,
  price_t30      REAL    NULL,
  reviewed_at    TEXT    NULL
)
```

### 3.3 两条设计约束

1. **`Position` 不落库**，由 `purchase_lots` 实时推导（总克数 / 成本价 / 市值 / 浮盈亏 / 计划进度）——避免两处真相不一致。
2. **`evidence` 必须冻结当时的行情快照**。否则三个月后无法回答「当时凭什么让我买」。
3. **`price_at_advice / price_t1 / price_t7 / price_t30` 第一天就要存**。这是唯一能回答「我的建议准不准」的数据，后补代价极大。回访任务不需要新表，用 `WHERE price_t1 IS NULL AND created_at < ?` 扫即可。

---

## 4. 建议引擎

### 4.1 分层原则：规则出事实，LLM 只出表述

现在的分工是反的——判断整体交给 LLM。对「要不要通知」无所谓，对**「买多少克」是危险的，LLM 会算错数**。

```
MarketSnapshot + Position + Plan + UserProfile
      ↓  [Signals] 确定性规则  → 结构化事实（可单测、可回测、LLM 挂了也能用）
      ↓  [Advisor] LLM（可选）→ 组织成人话 + 排优先级
   AdviceRecord（冻结证据）→ NotificationService 投递
```

**算术绝不进 prompt**。克数、成本、盈亏、比例全部由代码算好。

### 4.2 建议动作枚举

`BUY_NOW` / `BUY_PARTIAL` / `WAIT` / `AVOID` / `HOLD` / `ADD` / `TAKE_PROFIT` / `STOP_LOSS`

> `should_alert` 这个布尔语义要退役：建议需要的是 **`action`**，不是"要不要发通知"。

### 4.3 建议产出是一个对象，不是字符串

```python
Advice(
    kind=POST_PURCHASE,
    action=ADD,
    target_grams=15.0,
    price_band=(905.0, 915.0),
    confidence=0.6,
    rationale="成本 928，现价 908（-2.2%），现价处近 90 日 12% 分位，波动率回落",
    signals=["long_term_low_3m", "cost_below_by_2pct"],
    evidence={...},
)
```

### 4.4 信号集

**不新增数据依赖**，沿用已有指标（`PriceSnapshot`：`statistics(24)` / `ma(5,10,20)` / `trend(6,24)` / `min_3m` / `min_6m` / `percentile`），只补两类新的：

- **持仓类**：成本价偏离度、盈亏比例、持仓占总资金比、分批进度
- **计划类**：本批是否到点、剩余额度、距上次买入价距离

---

## 5. 建仓方式评估（一次性 vs 分批）

**这是整个重构里最值得投入、也最能和普通行情 App 拉开差距的一点。**

### 5.1 原料已经齐备

- `data/prices.db` 约 154 MB，含 `d=1y` + `d=60d` 历史（`backend/service/history_import_service.py:49-71`）
- `backend/mapper/price_mapper.py:441-451` 的 `_resolve_bucket()` 已能按小时/天降采样
- `PriceSnapshot` 的 `statistics / trend / ma / percentile` 指标齐全

### 5.2 做法

`EntryStrategyEvaluator`：给定计划总克数 `G`，在历史上找**相似的波动率/趋势环境**，回测两种策略的持有成本：

```
lump_sum : 第 0 天一次买满 G
tranches : 分 N 批（N=2,3,4,5），触发条件为「跌 x%」或「每 k 天」
输出     : 平均成本差异、最坏情况、胜率
```

### 5.3 产出示例

> 「当前波动率处过去一年 70% 分位。历史上这种环境下，分 4 批比一次性买入的 30 天成本平均低 1.8%、最坏高 0.6% —— 建议分 4 批。」

可单测、可回放、不依赖 LLM。**建议必须带证据**，否则又是一个「仅供参考」。

---

## 6. 必须顺带修复的现存缺陷

调研中发现的真实问题，**不修的话新功能会直接踩坑**。

### 6.1 与新功能直接冲突（高优先级）

| # | 问题 | 证据 | 影响 | 状态 |
|---|---|---|---|---|
| 1 | **AI 缓存 key 只有 `symbol`，TTL 60 分钟** | `backend/service/ai_service.py:96` `cache_key=symbol` | 录入买入后 1 小时内拿到的仍是**买入前的旧建议** | 键已改为按 prompt 输入分桶（阶段 0.5）；**持仓并入键要等阶段 1** |
| 2 | **`_periodic_ai_check` 不传 `triggered_alerts`** | `backend/service/monitor_service.py:168` 调用时未传 | 但 `SYSTEM_PROMPT` 开头断言「系统已触发价格报警条件」（`ai_service.py:17-39`）→ 周期分析 prompt 自相矛盾，模型倾向回 `should_alert: false` | 待阶段 2 重写 prompt 时解决 |
| 3 | **去重逻辑在活路径上从未被调用** | `_should_send_alert`（`alert_service.py:61-84`，10 分钟冷却）只被那 8 个已注释的检查调用 | 价格一旦低于阈值，**每 10 秒重新报警**；AI 不可用时刷屏 | ✅ **已修复**（阶段 0.5，`service/send_gate.py`） |
| 4 | **`ai_config.enabled` 从未被检查** | `backend/models/system_settings.py:26` | 设置页能关，代码里没人读 | 待处理 |

### 6.2 建议一并收敛（中低优先级）

| # | 问题 | 证据 |
|---|---|---|
| 5 | **`urgency` 算完就丢** | AI 的 `urgency` 只在日志出现（`monitor_service.py:147`、`:177`），`alert_level` 恒为 `"warning"`，永不落库、不进模板 |
| 6 | **`notification_send_logs` 建表语句重复定义在两处** | `backend/mapper/system_settings_mapper.py:184-201` 与 `backend/mapper/notification_stats_mapper.py:24-41` → 漂移风险，收敛到一处 |
| 7 | **`message_config` 六个字段存了但渲染器从不读** | `backend/utils/message_template.py` 全用硬编码模板 → 接上或删掉 |
| 8 | **`_is_in_cooldown` 定义了从没调用** | `backend/service/monitor_service.py:206-210` | ✅ **已删除**（阶段 0.5，由 `SendDeduplicator` 取代） |
| 9 | **`ai_call_logs.triggered_alerts` 恒为 NULL** | 写日志时固定传 `None` |

---

## 7. 落地路径

每步都能独立上线、不破坏现有功能。

| 阶段 | 内容 | 可独立交付的价值 |
|---|---|---|
| **0 · 抽概念不改行为** | 字符串 → 结构化 `Signal`；`PriceSnapshot` → 可序列化 `MarketSnapshot` | 前端零改动，行为完全一致 |
| **0.5 · 发送策略闸门** | 见配套文档 [send-policy-plan.md](./send-policy-plan.md)。**不依赖持仓域，可独立先做** | ✅ **已完成** — 立刻消灭周末/休市轰炸 |
| **1 · 持仓域** | `portfolio.db` + `PortfolioService` + `PositionCalculator`；API `/api/portfolio/{lots,plans,summary}`；前端「我的持仓」+ 买入录入 | ✅ **已完成**（后端 + 前端）—— 可看成本价与浮盈亏 |
| **2 · 建议引擎** | `AdviceEngine` + `strategies/{pre_purchase,post_purchase,plan_execution}`；`advice_records`；通知模板从「报警」改「建议」 | ✅ **后端闭环已完成**（见 §12、§13）；前端待做 |
| **3 · 建仓方式评估** | `EntryStrategyEvaluator` + 历史回测（可与 2 并行） | ✅ **已完成**（见 §15）—— 一次性 vs 分批有量化依据 |
| **4 · 调度与信息架构** | 多触发器 + T+n 回访；首页改为「持仓盈亏 → 当前建议（含证据）→ 行情」 | 🔶 **调度与死代码清理已完成**（见 §16、§17、§18）；信息架构打磨未做 |

### 7.1 建议的 MVP 范围（阶段 1 就能用）

1. `portfolio.db` + 买入录入（含补录历史）→「我的持仓」页：总克数 / 成本价 / 浮盈亏
2. `GET /api/advice/now` **手动**接口：持仓 + 行情 → 一条结构化建议（**先纯规则、不接 LLM**）
3. 首页顶部从「行情看板」改为「**持仓卡 + 当前建议卡**」

跑通之后才能真正判断「建议有没有用」，再决定是否投入回测和 LLM 表述层。

---

## 8. 服务分层与新增文件

```
backend/
  utils/market_session.py          # 见配套文档
  service/portfolio/
    portfolio_service.py           # lots/plans CRUD + position 计算入口
    position.py                    # Position 数据类 + 计算（纯函数，好测）
  service/advice/
    advice_engine.py               # 编排：context → signals → advisor → AdviceRecord
    context.py                     # AdviceContext（冻结快照 + 持仓 + 计划 + 偏好）
    signals.py                     # 确定性信号
    advisor.py                     # LLM 表述层（复用 ModelPool）
    entry_strategy.py              # 一次性 vs 分批 回测
    strategies/
      pre_purchase.py
      post_purchase.py
      plan_execution.py
  models/portfolio.py              # Pydantic
  models/advice.py
  mapper/portfolio_mapper.py       # portfolio.db
  mapper/advice_mapper.py
  controller/portfolio_controller.py
  controller/advice_controller.py
```

### 8.1 可直接复用、基本不动

- `ModelPool` / `backend/service/model_pool_engine.py` —— 多供应商 + 重试 + failover，正是建议引擎需要的
- `NotificationService` + `channels/` + `message_template.py` —— 投递管道完整，只需把 `AlertData`（`backend/channels/base.py:15-23`）扩展为 `AdviceData` 并改模板占位符
- `PriceMapper` / `PriceSnapshot` —— 指标体系完备
- 汇率折算、伦敦金对照、交易日历 —— 建议质量的关键输入，已有
- `SystemSettingsService` 单例 + 分表配置模式（沿用；**但持仓数据不要放进去**）
- 前端 `StatisticCard` / `TrendBadge` / `TimeRangeFilter` / 各图表组件
- `backend/mapper/price_mapper.py` 的只读查询体系

### 8.2 建议不动

`prices` / `exchange_rate_history` / `model_pool` 三个库的表结构。

---

## 9. 前端改动清单

遵循现有约定：**无分号、单引号、printWidth 100、无尾逗号**（`frontend/.prettierrc.json`）；`<style lang="scss" scoped>` + 只用 `var(--…)` CSS 变量；**全中文 UI**；页面 `max-width: 1200px`。

### 9.1 新增

| 文件 | 用途 |
|---|---|
| `frontend/src/api/modules/portfolio.ts` | `portfolioApi` |
| `frontend/src/api/modules/advice.ts` | `adviceApi` |
| `frontend/src/views/Portfolio.vue` | 持仓总览 + 批次表 + 录入入口 |
| `frontend/src/views/AdviceHistory.vue` | 建议历史 + 有效性（T+1/T+7/T+30） |
| `frontend/src/components/AdviceCard.vue` | 建议卡：action 标签、目标克数、价位区间、理由、证据折叠 |
| `frontend/src/components/PositionSummary.vue` | 总克数 / 成本价 / 市值 / 浮盈亏 |
| `frontend/src/components/LotFormDialog.vue` | 买入录入/编辑 |
| `frontend/src/components/settings/AdviceSettings.vue` | 建议策略配置 |

### 9.2 修改

- `frontend/src/views/DashBoard.vue` —— 顶部插入持仓卡与建议卡
- `frontend/src/router/index.ts` —— 注册 `/portfolio`、`/advice-history`
- `frontend/src/layout/AppSidebar.vue` —— 菜单分组调整
- `frontend/src/views/SystemSettings.vue` —— 注册 advice 设置页

### 9.3 复用

`useSettingsGroup(fetchFn, updateFn)`（`frontend/src/composables/useSettings.ts`）处理新配置页；轮询沿用 `watch(autoRefresh, …, { immediate: true })` + `onUnmounted` 清理的模式。

---

## 10. 待决问题

1. **推送节奏**：建议**只在 `action` 变化、或价格偏离上次建议超过阈值时推**，而不是现在的「每 5 分钟一次」。是否认可？
2. **是否引入「总可投资金 + 目标克数」配置**？没有它就无法回答「这次该买多少克」，只能给方向。
3. **建议是否要人工确认**（`delivered → acted`，记录「我照做了」）？这是评估建议有效性的基础，建议要。
4. **手动请求建议**（点一下「现在该不该买」）是否第一阶段就上？建议要——它让闭环在推送策略未定之前就能用。

---

## 11. 实施记录（阶段 1 · 持仓域，已完成）

记录日期：2026-10-03。后端与前端均已落地，30 项后端测试与前端 type-check / lint / prettier 全绿。

### 11.1 排期调整：阶段 0 并入阶段 2

阶段 0（字符串 → 结构化 `Signal`、`PriceSnapshot` → 可序列化 `MarketSnapshot`）**推迟到阶段 2**。
原因：这两个结构真正的消费方是建议引擎；现在做等于先重构 `AlertService`，而阶段 2 本来就会
用建议引擎取代它，属于返工。`MarketSnapshot` 的序列化会在阶段 2 冻结 `advice_records.evidence`
时一并落地。

### 11.2 改动清单

**新增（后端）**

| 文件 | 作用 |
|---|---|
| `backend/models/portfolio.py` | 买入批次 / 购买计划 / 持仓视图 / 计划进度 / 总览 的 Pydantic 模型 |
| `backend/service/position.py` | `compute_position`、`compute_plan_progress`、`summarize_totals` —— **纯函数，不碰数据库** |
| `backend/mapper/portfolio_mapper.py` | `portfolio.db` 两张表 + CRUD（走 `_connect()`，退出必定 close） |
| `backend/service/portfolio_service.py` | 编排、校验与模型转换 |
| `backend/controller/portfolio_controller.py` | 9 个接口 |
| `backend/test/test_portfolio.py` | 28 项用例 |

**新增（前端）**

| 文件 | 作用 |
|---|---|
| `frontend/src/api/modules/portfolio.ts` | `portfolioApi` + 全部类型 |
| `frontend/src/views/PortfolioOverview.vue` | 持仓总览 + 计划表 + 买入记录表 + 计划创建弹窗 |
| `frontend/src/components/PositionSummary.vue` | 持仓克数 / 成本价 / 市值 / 浮盈亏 四张卡 |
| `frontend/src/components/LotFormDialog.vue` | 买入录入（含「按总金额反推单价」） |

**修改**

| 文件 | 改动 |
|---|---|
| `backend/config.py` | 新增 `PORTFOLIO_DB_FILE` |
| `backend/mapper/price_mapper.py` | 新增 `get_latest_price(symbol)` —— 持仓市值用，走 `idx_prices_symbol_ts` |
| `backend/app.py` | 注册 portfolio 路由（45 → 50 条 API 路径） |
| `frontend/src/router/index.ts` | 新增 `/portfolio` |
| `frontend/src/layout/AppSidebar.vue` | 「监控与数据」组内新增「我的持仓」 |
| `frontend/src/layout/AppLayout.vue` | 面包屑标题映射 |

### 11.3 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/portfolio/lots` | 买入流水，按买入日期正序，可按 `symbol` 过滤 |
| POST | `/api/portfolio/lots` | 记一笔买入 |
| PUT | `/api/portfolio/lots/{id}` | 部分更新（只改传入的字段） |
| DELETE | `/api/portfolio/lots/{id}` | 删除 |
| GET | `/api/portfolio/plans` | 计划列表，可按 `symbol` / `status` 过滤 |
| POST | `/api/portfolio/plans` | 新建计划（`tranches=1` 即一次性） |
| PUT | `/api/portfolio/plans/{id}` | 更新（含暂停/启用） |
| DELETE | `/api/portfolio/plans/{id}` | 删计划但**保留**买入记录，关联置空 |
| GET | `/api/portfolio/summary` | 持仓总览：各品种持仓 + 计划进度 + 合计 |

### 11.4 与计划的偏差（均已确认合理）

| 计划 | 实际 | 原因 |
|---|---|---|
| `service/portfolio/` 包 | 扁平的 `portfolio_service.py` + `position.py` | 仓库里 15 个 service 都是单文件；只有阶段 2 的建议引擎（6+ 文件）才值得开包 |
| 前端 `views/Portfolio.vue` | `views/PortfolioOverview.vue` | 项目 eslint 开了 `vue/multi-word-component-names`，仓库内无任何 `eslint-disable`，且其它视图都是多词名 |
| — | 新增 `PriceMapper.get_latest_price()` | 原有没有「取最新价」的方法，持仓市值必须用它 |

### 11.5 已确认的成本口径

- `总成本 = Σ(克数 × 单价)`，**手续费只记录、不摊入成本**；`total_fee` 单独返回。
- **拿不到行情时市值/盈亏返回 `None` 而不是 `0`** —— `0` 会被读成「刚好持平」，
  跨品种合计也一样（任一品种无行情则合计返回 `None`，不静默少算）。

### 11.6 尚未做的部分（明确留给后续阶段）

1. **卖出 / 减仓**：`purchase_lots` 只记买入，因此**卖出后持仓会偏大**。
   若需要，加一张 `sell_lots` 表即可，不需要迁移现有表；但盈亏口径（先进先出还是移动平均）
   需要先定。
2. **`GET /api/advice/now` 手动建议接口**（MVP 第 2 项）—— 属于阶段 2。
3. **首页顶部「持仓卡 + 建议卡」**（MVP 第 3 项）—— 属于阶段 2 / 阶段 4；
   当前持仓只在 `/portfolio` 页展示。
4. **「总可投资金 + 目标克数」配置**（§10 第 2 条）—— 阶段 2 给「这次买多少克」时再加。
5. **侧边栏信息架构重做** —— 阶段 4。当前只是把「我的持仓」放进了「监控与数据」组。

---

## 12. 实施记录（阶段 2 · 建议引擎，引擎与接口已完成）

记录日期：2026-10-03。后端建议引擎、持久化与全部接口已落地；48 项新用例全绿。

### 12.1 排期说明：阶段 0 在此落地

阶段 0 的「`PriceSnapshot` → 可序列化」在这里实现为
`service/advice/context.py` 的 `MarketIndicators`：它一次性提取全部指标，
`to_dict()` 的结果冻结进 `advice_records.evidence`。这是「建议必须可回溯」的基础。

「字符串 → 结构化 `Signal`」也没有单独重构 `AlertService`，而是直接由新的
`signals.py` 产出结构化信号 —— 旧的那条路径会在 12.5 的整合中被替换掉。

### 12.2 改动清单

**新增**

| 文件 | 作用 |
|---|---|
| `backend/models/advice.py` | `AdviceKind` / `AdviceAction` / `AdviceStatus` / `Signal` / `AdvicePrefs` / `AdviceDraft` / `AdviceRecord` |
| `backend/service/advice/context.py` | `MarketIndicators`（行情快照 + 序列化）、`PlanState`（计划是否到点）、`AdviceContext` |
| `backend/service/advice/signals.py` | 确定性信号（行情 / 持仓 / 计划三类），阈值集中在文件顶部 |
| `backend/service/advice/strategies/` | `common.py`（建议克数、价位、置信度等**算术**）、`pre_purchase.py`、`post_purchase.py`、`plan_execution.py`、调度 |
| `backend/service/advice/advisor.py` | LLM 措辞层，硬约束「不得改结论、不得算数」 |
| `backend/service/advice/advice_engine.py` | 编排、落库、历史、生命周期、有效性回访 |
| `backend/mapper/advice_mapper.py` | `advice_records` 表 + T+1/T+7/T+30 回访追踪 |
| `backend/controller/advice_controller.py` | 7 个接口 |
| `backend/test/test_advice.py` | 48 项用例 |

**修改**

| 文件 | 改动 |
|---|---|
| `backend/mapper/system_settings_mapper.py` | 新增 `advice_config` 表 + 默认行 + 读写方法 |
| `backend/models/system_settings.py` | 新增 `AdviceConfigModel` |
| `backend/service/system_settings_service.py` | `get_advice_config` / `update_advice_config` |
| `backend/controller/system_settings_controller.py` | `GET/PUT /settings/advice` |
| `backend/service/ai_service.py` | 新增通用 `complete()`；**修复缺陷 #4** —— `ai_config.enabled` 此前从未被任何代码检查 |
| `backend/app.py` | 注册 advice 路由（50 → 58 条 API 路径） |

### 12.3 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/advice/now` | **手动请求建议**（MVP 第 2 项）。`fast=true` 跳过 AI 措辞 |
| GET | `/api/advice/history` | 建议历史，分页，可按品种 / 语境 / 状态过滤 |
| GET | `/api/advice/{id}` | 单条建议（含冻结的 evidence 与信号） |
| POST | `/api/advice/{id}/ack` | 标记已读 |
| POST | `/api/advice/{id}/acted` | **记录「我照做了」**，可回填实际成交的 lot id |
| POST | `/api/advice/reviews/refresh` | 回填到期的 T+1/T+7/T+30 价格 |
| GET | `/api/advice/reviews/stats` | 建议有效性统计 |
| GET/PUT | `/api/settings/advice` | 偏好配置（总资金 / 目标克数 / 风险偏好 / 是否用 LLM / 推送阈值） |

> 路由顺序有讲究：`/now`、`/history`、`/reviews/*` 必须声明在 `/{advice_id}` **之前**，
> 否则会被路径参数吃掉。

### 12.4 关键设计决定

| 决定 | 取值 | 理由 |
|---|---|---|
| 策略优先级 | **计划执行 > 购买后 > 购买前** | 用户已定好分批计划时，系统该帮他执行，而不是另起炉灶给一个不相干的买点 |
| 建议动作 | 枚举 8 个（`BUY_NOW`/`BUY_PARTIAL`/`WAIT`/`AVOID`/`HOLD`/`ADD`/`TAKE_PROFIT`/`STOP_LOSS`） | 取代无主体的字符串文案与 `should_alert` 布尔 |
| 没配偏好时 | **只给方向，不给克数**（`target_grams=None`） | 不能凭空编一个数字；提示用户去补配置 |
| 拿不到行情时 | 购买前 → `WAIT`；购买后 → `HOLD` | 不假装能判断 |
| 深亏但趋势未走坏 | `HOLD` 而不是 `STOP_LOSS` | 避免在非趋势性下跌中建议割肉 |
| 止盈 / 止损 | 分别卖出 1/3 与 1/2 | 分批操作，不一次清仓 |
| LLM 缓存键 | prompt 的 SHA-1 前 16 位 | 措辞必须与输入严格对应，不能复用别人的理由 |
| AI 总开关 | 在 `_ensure_model_pool` 统一拦截 | 一处修复，`analyze` 与 `complete` 两个入口都遵守（缺陷 #4） |

### 12.5 剩余部分

1. ~~**`MonitorService` 整合**~~ → 已在 §13 完成。
2. ~~**通知模板从「报警」改「建议」**~~ → 已在 §13 完成。
3. **前端**：`AdviceCard.vue`、建议历史页、首页「持仓卡 + 建议卡」、
   `components/settings/AdviceSettings.vue`。 → 已在 §14 完成。
4. ~~**`suppressed_reason` 落库**~~ → 已在 §13 完成。

### 12.6 一个实现中发现并修掉的死代码

`pre_purchase` 策略里原本有两个 `AVOID` 分支（仓位超 100%、额度用尽）**永远不可达** ——
购买前策略的前提就是「没有持仓」，此时市值与成本必然为 0。
已改成有意义的可达条件：**价格已高于近 180 日低点 15% 以上 + 处在近 24 小时区间上沿 +
中期趋势向上 → `AVOID`（别追高）**，并新增对应信号 `far_from_long_term_low`。

### 12.7 验证方式

```bash
cd backend
python -m test.test_advice      # 48 项
python -m test.test_portfolio   # 28 项（回归）
python -m test.test_market_session      # 15 项（回归）
python -m test.test_monitor_send_gate   # 10 项（回归）
python -m test.test_sqlite_connections  #  3 项（回归）
```

实测一条真实产出的建议（行情 909、目标 60g、无持仓）：

> action=`BUY_PARTIAL`，target_grams=20.0，confidence=0.5
> 理由：「现价 ¥909.00/克，距近 90 日低点 +1.00%，中期趋势上涨。处于近 24 小时区间上沿，
> 不建议一次性买满，先买约 20.0g（约 1/3 额度），剩余额度留给更低的位置」
> 信号：`near_24h_high` / `trend_short_up` / `trend_mid_up` / `no_position` / `no_plan`

计划存在时正确切换到 `plan_execution`，并按每批克数给出 25g（100g / 4 批）。

---

## 13. 实施记录（阶段 2 · 后端闭环：监控整合 + 建议通知）

记录日期：2026-10-03。建议从「只有手动请求才生成」变成「监控循环自动生成并投递」，
通知也从「报警」改成了「建议」。**后端闭环完成。**

### 13.1 监控循环的变化

原来：**价格越线 → 问 AI 要不要发通知 → 发一条无主体的报警文案**

现在：

```
_tick()
  ├─ 抓价、存库
  ├─ 时段闸门 policy_decision()
  │    └─ SILENT → 记录抑制原因后返回（不评估建议、不调 AI）
  ├─ 节流：距上次评估不足 ai_check_interval_minutes → 返回
  ├─ advice_engine.compute()        ← 信号 / 策略 / 证据，全部由规则算
  ├─ 推送节流 _should_push()         ← 动作变了？或价格偏离上次推送 ≥ 阈值？
  │    └─ 否 → 落库为 suppressed(duplicate)，不推送
  ├─ 终审闸门 send_gate.review()     ← LOW_FREQ 优先级过滤 + 冷却去重
  │    └─ 否 → 落库为 suppressed(low_priority / duplicate)
  └─ 落库 + notification_service.send_advice()
```

三个关键点：

- **被抑制的建议也落库**，带 `suppressed_reason` —— 「当时为什么没发」以后查得到；
- **推送节流的比较基准来自数据库**（`AdviceMapper.last_pushed`，排除 suppressed），
  所以**重启后不会立刻重复推送**；
- `MonitorService` 不再直接依赖 `AlertService` 与 `AIAnalysisService`：规则在
  `signals.py` / `strategies/`，措辞由 `advisor` 负责。

为了让「先算出来、判断值不值得推、再决定以什么状态落库」成为可能，
`AdviceEngine` 拆成了 `compute()` / `save()`，`generate()` 是二者的便捷组合，
`/advice/now` 的行为不变。

### 13.2 通知从「报警」改「建议」

| 改动 | 说明 |
|---|---|
| `channels/base.py` | 新增 `AdvicePayload`；`AlertData` 增加可选的 `advice` 字段与 `is_advice` 属性。**两条路径共用同一套渠道投递逻辑**，报警功能不受影响 |
| `utils/message_template.py` | 新增 `WECHAT_ADVICE_TEMPLATE` 与 `format_advice()`；动作→中文标签/颜色的映射放在这里（展示层职责，不进数据模型） |
| `templates/email_advice.html` | 新增建议版邮件模板（自包含内联样式，不依赖外部 CSS） |
| `service/notification_service.py` | 抽出 `_dispatch()`；新增 `send_advice()`。持仓上下文**取自建议冻结的 `evidence`**，保证「消息里说的持仓」与「当时生成建议用的持仓」一致 |
| `models/advice.py` | 新增 `ACTION_URGENCY`（供闸门判优先级）与 `ACTION_ALERT_LEVEL`（供通知日志与前端上色） |

实测产出的消息（企业微信 markdown）：

```
## [建议] 黄金持仓建议

**品种**：黄金延期
**当前价格**：911.00
**伦敦金参考**：¥531.2/g（$2300.0）
**建议动作**：建议分批买入
**建议数量**：20.0 克
**建议价位**：¥903.71 ~ ¥918.29
**持仓状态**：暂无持仓

### 判断依据
- 现价 ¥911.00 已跌破设定的安全线 ¥915.00
- 处于近 24 小时区间上沿（100% 位置）
- 当前没有持仓
- 没有进行中的购买计划

### 说明
现价 ¥911.00/克，距近 90 日低点 +1.22%，中期趋势上涨。处于近 24 小时区间上沿，
不建议一次性买满，先买约 20.0g（约 1/3 额度），剩余额度留给更低的位置

---
*建议由规则计算生成，仅供参考，不构成投资建议*
```

### 13.3 保留用户已有的安全线

原 `alert_service` 里**唯一活着的规则**是「现价低于 `absolute_low_price` 就报警」。
改成建议流程后这条线如果不迁移就会**静默失效**，所以：

- `AdvicePrefs` 新增 `absolute_low_price`，由 `get_prefs()` 从原来的
  `alert_config.absolute_low_price` 读取；
- `signals.py` 新增 `absolute_low` 信号（severity=`critical`）。

**配置值不用改**，语义从「独立报警」变成「参与建议判断的一条信号」。

### 13.4 实现中发现并修掉的问题

**企业微信 markdown 转义过度。** `_escape_markdown` 早先把 `.` `+` `-` `!` `=` 等
一并转义，于是「¥911.00」会变成「¥911\.00」、「+1.22%」变成「\+1.22%」。
企业微信的 markdown 是简化版、**不解析反斜杠转义**，所以那些反斜杠会原样显示给用户。
已把转义集合收窄到真正有语法含义的字符：`` \ * _ ` [ ] # ``。
报警路径复用同一个函数，因此一并变干净。

### 13.5 遗留：报警路径已成为死代码

以下代码现在没有生产调用方，可以在清理阶段一并删掉（暂时保留以便对照）：

- `backend/service/alert_service.py`（8 个已注释的规则算法 + 绝对低价检查）
- `NotificationService.send_alert()`、`MessageTemplate.format_alert()`
- `backend/templates/email_alert.html`
- `SendGate` 之外的 `send_gate.alert_dedup_key()`

> ⚠️ `alert_config` 表**仍在用** —— 它的 `absolute_low_price` 通过 `AdvicePrefs`
> 参与建议判断（见 §13.3），**不要连表一起删**。

### 13.6 验证方式

```bash
cd backend
python -m test.test_advice_notification   # 10 项（新增）
python -m test.test_monitor_send_gate     # 13 项（已按建议流程重写）
python -m test.test_advice                # 50 项
python -m test.test_portfolio             # 28 项（回归）
python -m test.test_market_session        # 15 项（回归）
python -m test.test_sqlite_connections    #  3 项（回归）
```

共 **119 项全部通过**。另外用一个真实 `MonitorService` + 真实 `AdviceEngine` +
记录渠道跑通了完整回路，验证：正常时段生成并投递 → 巡检间隔内不重复评估 →
动作未变时抑制为 `duplicate` → 周末静默不落库 → `last_pushed` 正确跳过 suppressed 记录。

---

## 14. 实施记录（阶段 2 · 前端）

记录日期：2026-10-03。建议第一次能在界面上看到，而不只是从微信/邮件里读。

### 14.1 新增

| 文件 | 作用 |
|---|---|
| `frontend/src/api/modules/advice.ts` | `adviceApi`：`getNow` / `getHistory` / `get` / `acknowledge` / `markActed` / `refreshReviews` / `getReviewStats`，以及建议偏好配置的读写 |
| `frontend/src/utils/adviceHelpers.ts` | 动作→中文标签/标签样式的映射、`evidenceRows()`（把冻结的 evidence 摊成可读键值行）、`reviewMoveText()`（结合动作方向解读回访涨跌） |
| `frontend/src/components/AdviceCard.vue` | 建议卡：动作徽标、建议数量/价位/置信度、理由、判断依据（可折叠）、**当时行情与持仓**（可折叠，用于回溯）、已读/已执行、重新生成 |
| `frontend/src/views/AdviceHistory.vue` | 建议历史：有效性统计卡（T+1/T+7/T+30）、语境/状态筛选、分页表格，展开行内嵌完整 `AdviceCard` |
| `frontend/src/components/settings/AdviceSettings.vue` | 建议配置：总资金、目标克数、目标仓位、风险偏好、是否用 AI 润色、重复推送价格阈值 |

### 14.2 修改

| 文件 | 改动 |
|---|---|
| `frontend/src/views/DashBoard.vue` | 顶部插入**持仓卡 + 当前建议卡**（MVP 第 3 项） |
| `frontend/src/views/SystemSettings.vue` | 「核心业务」组新增「建议配置」页 |
| `frontend/src/router/index.ts`、`AppSidebar.vue`、`AppLayout.vue` | 新增 `/advice-history`「建议历史」及面包屑 |

### 14.3 一个刻意的设计决定：首页不生成建议

`GET /api/advice/now` **会落库**。如果首页每次 10 秒轮询都调它，一天会写进
8000+ 条建议记录，把 `advice_records` 彻底淹掉。

所以首页的行为是：

- **展示**用 `GET /api/advice/history?page_size=1` —— 只读最近一条，由监控循环生成；
- **生成**只在用户点「现在该不该买？」时发生（`getNow({ fast: true })`），
  并要求二次确认式的显式动作。

这样「建议记录」的数量与监控循环的推送节奏一致，历史页才有意义。

### 14.4 验证

```bash
cd frontend
npx vue-tsc --noEmit -p tsconfig.app.json   # exit 0
npx eslint <新增与改动的文件>                # exit 0
```

> 关于 prettier：仓库本身并非 prettier-clean（实测 HEAD 上的 `DashBoard.vue`、
> `router/index.ts`、`AppSidebar.vue`、`AppLayout.vue`、`SystemSettings.vue`
> **原本就与 prettier 输出不一致**），所以没有对既有文件做批量重排，避免制造无关 diff；
> 只对本次新增的文件执行了 `prettier --write`。

### 14.5 阶段 2 完成情况

| 项 | 状态 |
|---|---|
| 建议引擎（信号 / 策略 / 证据 / 措辞） | ✅ |
| `advice_records` 持久化 + 有效性追踪 | ✅ |
| 建议接口（8 个） | ✅ |
| 监控循环整合（自动生成 + 三闸门） | ✅ |
| 通知从「报警」改「建议」 | ✅ |
| 前端（建议卡 / 历史 / 首页 / 配置页） | ✅ |

### 14.6 后续阶段

- **阶段 3 · 建仓方式评估**：`EntryStrategyEvaluator` —— 用 `prices.db` 里的历史回测
  「一次性 vs 分 2/3/4/5 批」的成本差异，让「分批还是一次性」的建议带证据。
  这是计划里认为最值得投入的差异化能力，目前仍是空白。
- **阶段 4 · 调度与信息架构**：多触发器（价格 / 定时 / 事件回访 / 手动）+ T+n 回访调度；
  侧边栏与首页信息架构的进一步重做。
- **清理**：删掉已死的报警路径（见 §13.5）。

---

## 15. 实施记录（阶段 3 · 建仓方式评估）

记录日期：2026-10-03。**「分批还是一次性」第一次有了量化证据**，不再是经验规则。

### 15.1 做法

`service/advice/entry_strategy.py`：取日线序列 → 找出与当前**波动率相似**的历史环境 →
在同一批样本上同时模拟几种建仓方式 → 比较持有到期末的每克平均成本。

| 方案 | 说明 |
|---|---|
| `lump_sum` | 第 0 天一次买满（基准） |
| `interval(N)` | 分 N 批，按固定时间间隔买入 |
| `drop_pct(N)` | 分 N 批，按「较上一批跌 1%」触发补仓；期末未触发的部分按期末价补足，**否则与一次性不可比** |

N 取 2/3/4/5。核心计算全是**纯函数**（输入是价格序列），只有 `fetch_series()` 碰数据库，
所以回测逻辑可以脱离数据库单测。

### 15.2 决策规则

分批要同时满足两条才被推荐：

1. **平均成本更低**（`avg_cost_diff_pct < 0`）；
2. **最坏情况在容忍度内**（`worst_case_pct <= tolerance`）。

容忍度**自适应**：`tolerance = clamp(一次性买入价的离散度, 1.5%, 6.0%)`。
含义是 —— 一次性买入价本来就忽高忽低时，分批多付一点并不值得计较；但也不能无限放宽，
否则等于放弃风险约束。

> 这里踩过一个坑：最初我按 `avg_diff + 0.5 × worst_case` 打分，结果**分批几乎永远不被推荐**
> —— 因为基准（一次性）的差异恒为 0，任何一次不利的尾部样本都会把分批压下去。
> 改成「平均更便宜 + 最坏情况有上限」这条显式规则后才合理。
> 同时把**一次性也放进候选列表**，否则「分批永远赢」（它的 diff 恒为 0），判断没有对照物。

### 15.3 实测输出

注入 250 天合成日线（`drift=-0.3%/天`，`vol=0.6%/天`）：

```
样本数=200  当前波动率=0.606%（历史 65% 分位）
一次性买入价的离散度=16.85% → 最坏情况容忍度=6.0%
  一次性买入              平均  +0.000%  最坏  +0.000%  胜率   0.0%
  分 5 批（按时间）         平均  -3.215%  最坏  +0.583%  胜率  95.5%
  分 4 批（按时间）         平均  -2.826%  最坏  +1.269%  胜率  94.0%
  分 3 批（按时间）         平均  -2.693%  最坏  +0.768%  胜率  94.5%
  分 5 批（按跌幅）         平均  -2.653%  最坏  +0.087%  胜率  99.0%
  分 4 批（按跌幅）         平均  -2.051%  最坏  -0.069%  胜率 100.0%
结论：分 5 批
```

上涨行情（`drift=+0.25%/天`）下同一套逻辑正确翻转为：

```
  一次性买入              平均  +0.000%
  分 2 批（按时间）         平均  +1.738%  最坏  +3.756%  胜率 0.0%
  分 3 批（按时间）         平均  +2.334%  最坏  +5.456%  胜率 0.0%
结论：分 1 批（一次性）—— 「表现最好的分批方案平均成本仍比一次性高 1.74%」
```

**建议里对它的引用**（80g 目标、分 5 批 → 首笔 16g）：

> 现价 ¥543.55/克，距近 90 日低点 +0.07%，中期趋势横盘。在过去 365 天里找到 200 个与
> 当前相似的市场环境（当前波动率 0.61%，处于历史 65% 分位）：分 5 批（按时间）的平均
> 持有成本比一次性买入低 3.21%，最坏情况下贵 0.58%（容忍度 6.00%），跑赢一次性的概率
> 96%，因此建议分批买入。建议先买约 16.0g（约 1/5 额度），剩余额度按同样节奏分批补入

### 15.4 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/advice/entry-strategy` | 回测「一次性 vs 分批」。参数 `symbol` / `lookback_days`（60-1095）/ `horizon_days`（5-180） |

回测结论会**冻结进 `advice_records.evidence.entry_strategy`**，前端的证据折叠区新增了
「建仓方式回测样本 / 回测建议 / 波动率历史分位」三行。

### 15.5 性能与缓存

`get_chart_series(hours=8760)` 会把一年上百万行 tick 按天聚合，在 154 MB 的
`prices.db` 上不是免费操作。而日线序列**一天才变一次**，所以 `EntryStrategyEvaluator`
加了 30 分钟 TTL 缓存，键只有「品种 × 回看天数」两种，不会无界增长。

### 15.6 诚实优先

样本不足时**明确说不知道**，而不是用几个样本编一个结论：

- 序列短于 `20（波动率窗口）+ horizon + 20（最少样本）` → `sufficient_data=False`，
  建议一次性，理由是「历史数据不足（只有 40 个数据点，至少需要 70 个）」；
- 相似环境样本少于 `MIN_SAMPLES=20` → 同样拒绝给结论。

`pre_purchase` 在这种情况下会退回「波动高/位置高就分 3 批」的经验规则，并在理由里说明
「历史数据不足以回测建仓方式」。

### 15.7 验证方式

```bash
cd backend
python -m test.test_entry_strategy        # 29 项（新增）
python -m test.test_advice                # 50 项（回归）
python -m test.test_advice_notification   # 10 项（回归）
python -m test.test_monitor_send_gate     # 13 项（回归）
python -m test.test_portfolio             # 28 项（回归）
python -m test.test_market_session        # 15 项（回归）
python -m test.test_sqlite_connections    #  3 项（回归）
```

共 **148 项全部通过**。其中包含手工可验算的算例（如 `window=[100,110,120,130,140]`
分 2 批 → 均价 110；`[100,99,...]` 跌 1% 触发 → 均价 99.5），以及
「上涨行情不该分批、下跌行情该分批、样本不足要诚实说不知道」这三条行为断言。

---

## 16. 实施记录（阶段 4 · 调度基础与回访自动积累）

记录日期：2026-10-03。阶段 4 的第一部分：**「建议准不准」的数据开始自动、正确地积累**。

### 16.1 先修一个会静默污染数据的问题

原来的 `refresh_reviews()` 是这样回填的：

```python
price = self.price_mapper.get_latest_price(record["symbol"])   # ← 用的是「现在」的价格
```

**这是错的。** T+1 回访要的是「建议发出**一天后**」的价格。如果进程停机几天后再回填，
最新价已经是一周后的价格了 —— T+1 会被写成一周后的价，而这个过程**不报错**，
只会静默污染「建议准不准」的统计。有效性数据是长期唯一的护城河，被污染就白攒了。

修法：新增 `PriceMapper.get_price_near(symbol, timestamp)` —— 取目标时点**当时**的价格
（优先该时刻之前的最后一条；若早于全部数据则取之后最近一条），
`refresh_reviews()` 改为按 `created_at + N 天` 算出目标时点再取价。

实测（建议发出于 10 天前，序列 T+0=900 / T+1=918 / T+2=930 / 今天=800）：

```
price_t1  = 918.0   （T+1 的价格，不是最新价 800）
price_t7  = 930.0   （T+7 时点之前最近一条）
price_t30 = None    （未到期）
```

回填结果也诚实区分了三种情况：`checked` / `filled` / `skipped`（目标时点无可用价格）。

### 16.2 回访进监控循环

`MonitorService._tick()` 新增 `_refresh_reviews_if_due()`，默认每小时回填一次。

**刻意放在时段闸门之外**：回填读的是历史价格，与当前是否休市无关 ——
周末和节假日恰恰是补齐回访的好时机。间隔大小也不影响正确性，
因为到期判定是按「建议发出时间 + N 天」算的，而不是按「距上次回填多久」。

在此之前只能手动调 `/advice/reviews/refresh`，实际上就没人会去调 ——
有效性数据永远不会积累。

### 16.3 定时任务收敛为 `DueTimer`

监控循环里原本有三四处各自维护 `_last_xxx` 时间戳再自己算 elapsed，既重复又不好测。
新增 `utils/due_timer.py` 统一成一个可测的小工具，并把四处都换了过去：

| 定时任务 | 间隔 | 原实现 |
|---|---|---|
| 设置热更新 | 60s | `_last_settings_refresh` + 手工比较 |
| 建议评估 | `ai_config.check_interval_minutes` | `_last_advice_time` + 手工比较 |
| **回访价格回填** | 3600s | **新增** |
| 日志清理 | 86400s | `check_count % (86400 // check_interval)` 取模 |

`DueTimer` 有两个刻意的行为：

- **从没跑过算到点** —— 进程启动后第一次巡检就补齐，不必等一个完整间隔；
- **改间隔不重置上次运行时间** —— 否则每次改配置都会立刻触发一次，
  在巡检类任务上会造成「改一次配置就多发一条」。

### 16.4 验证方式

```bash
cd backend
python -m test.test_review_scheduling     # 17 项（新增）
python -m test.test_entry_strategy        # 29 项（回归）
python -m test.test_advice                # 50 项（回归）
python -m test.test_advice_notification   # 10 项（回归）
python -m test.test_monitor_send_gate     # 13 项（回归）
python -m test.test_portfolio             # 28 项（回归）
python -m test.test_market_session        # 15 项（回归）
python -m test.test_sqlite_connections    #  3 项（回归）
```

共 **165 项全部通过**。另外用真实 `MonitorService` 复现了「宕机 10 天后重启」的场景，
确认 T+1 回填的是 918 而不是最新价 800，且重复回填不会改写已填的值。

### 16.5 阶段 4 剩余

1. **事件回访触发**：目前回访只回填价格，还不会**生成**一条「复盘建议」。
   产品原始需求是「建议会在用户购买黄金前后」—— 买后 T+1/T+7/T+30 主动给一条
   「你这笔买得怎么样、现在该怎么办」才是完整闭环。需要给 `advice_records`
   加 `subject_lot_id` / `review_horizon` 两列来标记「这条建议是针对哪笔买入的」。
2. **信息架构重做**：侧边栏与首页的进一步整理（阶段 4 原定内容）。
3. **清理**：删掉已死的报警路径（见 §13.5）。

---

## 17. 实施记录（阶段 4 · 事件回访触发）

记录日期：2026-10-03。**产品原始需求里「购买**后**」那一半补齐了** —— 买完不是结束，
系统会在 T+1 / T+7 / T+30 主动告诉用户这笔买得怎么样、现在该怎么办。

### 17.1 触发时机的设计（最容易做错的地方）

朴素做法是「`距今 >= N 天` 且还没复盘过就触发」。这会踩一个大坑：
**用户补录一笔三个月前的买入，会一次性被补出三条复盘**（T+1/T+7/T+30 全都满足），
补录历史等于被轰炸。

所以触发条件是 `距今 == N 天`，外加 `FOLLOWUP_CATCHUP_DAYS = 2` 天的追补窗口：

| 场景 | 结果 |
|---|---|
| 今天买入 | 明天触发 T+1 ✅ |
| T+1 那天进程停机，第 2 天恢复 | 仍在窗口内，补上 ✅ |
| 补录三个月前的买入 | 三个档位都早已过去，**不触发** ✅ |
| 一笔 7 天前的买入 | 只触发 T+7，不同时触发 T+1 ✅ |

### 17.2 复盘不自己判断动作

`strategies/review.py` **不另起一套动作判断**，而是复用常规调度
（`build_regular`：计划执行 → 购买后 → 购买前），只把理由换成针对这笔买入的交代。

理由：如果复盘自己判断，就会出现「复盘说补仓、常规建议说观望」这种自相矛盾的输出。
产品里同时存在两条建议时，它们必须说同一件事。

实测理由（昨天 950 买入 20g，现价 911）：

> 回访你在 2025-09-23 买入的 20g（成交价 ¥950.00/克）：到今天 T+1，这笔浮动 -4.11%。
> 持仓 30.0g，成本价 ¥926.67；……

注意「这笔浮动 -4.11%」说的是**这一笔自己的成交价**，与整体持仓成本（926.67）区分开。

### 17.3 被闸门拦下时不落库

复盘是「一次性事件」，靠 `has_review(subject_lot_id, horizon)` 保证不重复。
但如果被闸门拦下（例如国际金休市时的低优先级过滤）也落库，`has_review` 就会变真，
**这条复盘就永远丢了**。

所以刻意**不落库**：`has_review` 只认非 suppressed 的记录，
下一次巡检（仍在追补窗口内）会重试。

休市静默期则**根本不生成** —— 复盘内容依赖当前价格，闭市时价格是冻结的，
生成出来也只能说「观望」，留到开市后再做更合理。

另外单次巡检最多生成 `MAX_FOLLOWUPS_PER_TICK = 3` 条，避免首次上线时集中补发。

### 17.4 表结构迁移

`advice_records` 新增两列标记「这条建议是针对哪笔买入的」：

- `subject_lot_id INTEGER NULL`
- `review_horizon INTEGER NULL`

老库通过 `_migrate_columns()` 自动 `ALTER TABLE` 补列（沿用
`system_settings_mapper` 里已有的迁移写法），并对 `(subject_lot_id, review_horizon)`
建索引。迁移可重复执行。

### 17.5 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/advice/followups/pending` | 当前到点但还没生成复盘的「买入 × 档位」 |

### 17.6 验证方式

```bash
cd backend
python -m test.test_review_followup       # 26 项（新增）
python -m test.test_review_scheduling     # 17 项（回归）
python -m test.test_entry_strategy        # 29 项（回归）
python -m test.test_advice                # 50 项（回归）
python -m test.test_advice_notification   # 10 项（回归）
python -m test.test_monitor_send_gate     # 13 项（回归）
python -m test.test_portfolio             # 28 项（回归）
python -m test.test_market_session        # 15 项（回归）
python -m test.test_sqlite_connections    #  3 项（回归）
```

共 **191 项全部通过**。端到端跑通了：真实 `MonitorService` + 一笔昨天的买入
→ 生成并投递 T+1 复盘 → 渲染出消息 → 不重复 → 周末不生成但保留待办
→ 补录的三个月前买入不触发任何复盘。

### 17.7 阶段 4 剩余

1. **信息架构重做**：侧边栏与首页的进一步整理（阶段 4 原定内容）。
   当前首页已经是「持仓盈亏 → 当前建议（含证据）→ 行情」，
   建议卡与历史页也已就绪，剩下的主要是措辞与分组层面的打磨。
2. **清理**：删掉已死的报警路径（见 §13.5）。`alert_config` 表要留着。

---

## 18. 实施记录（阶段 4 · 清理死代码）

记录日期：2026-10-03。**报警路径整体移除** —— 留着会让人误以为它还在生效。

### 18.1 删掉的东西

| 对象 | 说明 |
|---|---|
| `backend/service/alert_service.py` | 整个文件：8 个已注释的规则算法 + 绝对低价检查 + 从未生效的 `_should_send_alert` |
| `NotificationService.send_alert()` | 已无调用方 |
| `MessageTemplate.format_alert()` + `WECHAT_MARKDOWN_TEMPLATE` + `_load_email_html_template()` | 报警文案渲染 |
| `backend/templates/email_alert.html` | 报警邮件模板 |
| `send_gate.alert_dedup_key()` | 报警文案归一化去重键（连 `re`/`_DIGITS` 一起） |
| `channels/base.py: AlertData` | 重命名为 `AdviceData`，并去掉 `alert_messages` / `suggestions` / `is_advice` —— 载荷只有建议一种形态了 |

两个渠道（企业微信 / 邮件）不再需要「是报警还是建议」的分支，直接渲染建议。

### 18.2 刻意保留的东西

| 对象 | 原因 |
|---|---|
| `alert_config` 表 | 它的 `absolute_low_price` 仍通过 `AdvicePrefs` 参与建议判断（§13.3） |
| `/settings/alert` 接口 + `AlertConfigModel` | 同上，设置页仍要能改这条安全线 |
| `AdviceData.alert_level` 这个名字 | 它对应通知日志列 `notification_send_logs.alert_level`，前端通知统计页仍在按它上色；改名收益不抵迁移成本 |

> ⚠️ **不要连 `alert_config` 表一起删。**

### 18.3 清理中发现并修掉的一个真问题

`alert_config.enable_absolute_alert` **从迁移到建议引擎之后就再没人读过**：

```python
absolute_low_price=float(alert_config.get("absolute_low_price") or 0.0),   # 只有这一行
```

也就是说，用户在设置页把「绝对低价报警」关掉，安全线**依然会参与建议判断** ——
与 §13.4 修掉的 `ai_config.enabled` 属于同一类问题：开关没人读。

修法：`AdvicePrefs` 增加 `absolute_alert_enabled`，`signals.py` 的 `absolute_low`
信号同时检查开关。实测：

```
打开：signals = ['absolute_low', 'near_24h_high', 'trend_short_up', ...]
关闭：signals = ['near_24h_high', 'trend_short_up', ...]
```

### 18.4 验证方式

```bash
cd backend
python -m test.test_market_session        # 14 项（移除 alert_dedup_key 用例）
python -m test.test_advice                # 51 项（新增开关用例）
python -m test.test_advice_notification   # 10 项（改为 AdviceData）
python -m test.test_review_followup       # 26 项（回归）
python -m test.test_review_scheduling     # 17 项（回归）
python -m test.test_entry_strategy        # 29 项（回归）
python -m test.test_monitor_send_gate     # 13 项（回归）
python -m test.test_portfolio             # 28 项（回归）
python -m test.test_sqlite_connections    #  3 项（回归）
```

共 **191 项全部通过**。另外用一段独立验证确认：

- 整个 FastAPI app 仍能导入（60 条 API 路径）；
- 被删的对象确实不存在了（`import service.alert_service` 失败、`hasattr` 均为 False）；
- 两条渲染路径都正常（企业微信 markdown、邮件 HTML 都能加载 `email_advice.html`）；
- 安全线开关真的生效。

### 18.5 整体进度

| 阶段 | 状态 |
|---|---|
| 0 · 抽概念 | 已并入阶段 2 落地 |
| 0.5 · 发送策略闸门 | ✅ |
| 1 · 持仓域 | ✅ |
| 2 · 建议引擎（含监控整合、通知改版、前端） | ✅ |
| 3 · 建仓方式评估 | ✅ |
| 4 · 调度（回访回填 + 事件回访）与清理 | ✅ |
| 4 · 信息架构打磨 | 未做（现状已可用，价值有限） |

**剩余可选项**：

1. **信息架构打磨** —— 首页已是「持仓盈亏 → 当前建议（含证据）→ 行情」，
   侧边栏也已把「我的持仓 / 建议历史」放在最前。剩下是措辞与分组层面的整理。
2. **卖出 / 减仓支持**（§11.6 第 1 项）—— `purchase_lots` 只记买入，
   **卖出后持仓会偏大**，盈亏口径（先进先出还是移动平均）需要先定。
   这是目前唯一已知的功能性缺口。
3. `chinese-calendar` 依赖升级（§7.5）—— 数据只到 2026 年，年底前需处理
   （代码已降级兜底，不会崩，但节假日判断会退化为仅按星期）。

---

## 19. 实施记录（用户反馈：建议配置看不到持仓入口）

记录日期：2026-10-03。起因是用户反馈：

> 我当前已经有持仓，但前端界面的建议配置不够直观或没有这个功能，无法填写我当前的持仓信息。

排查后确认**功能其实存在**（在「我的持仓」页逐笔录批次），但**入口不在用户会去找的地方**
—— 用户先去「建议配置」里找，那里什么都没有。同时顺带查实了两个从未生效的配置项。

### 19.1 两个「存得下、读得出、没人用」的字段

| 字段 | 原先的实际状况 |
|---|---|
| `target_position_ratio` | 只被读进 `AdvicePrefs` 就没了下文；真正判定「仓位偏重」的是 `signals.py` 里**硬编码的 `POSITION_RATIO_HIGH_PCT = 100.0`** —— 用户会在一个自己没设过、也改不了的阈值上收到提示 |
| `risk_level` | 同样只有定义、DDL 与读进 prefs，**没有任何消费者**；选保守还是进取对建议结果零影响 |

这是同一个坑的第三、四次（前两次是 `ai_config.enabled` 与 `enable_absolute_alert`）。
`target_position_ratio` 还是建议配置里**唯一没有说明文字**的字段。

### 19.2 「期初持仓」—— 让老持仓用户能一次填完

用户已经有持仓、且多半记不清每一笔的日期，逐笔录批次是不现实的。做法是新增
「期初持仓」概念，而不是另起一套「汇总持仓」：

| 方案 | 为什么不用 / 用 |
|---|---|
| 单独做一份「汇总持仓」 | 买入回访（T+1/T+7/T+30）与分批计划进度会**失去依据**，等于停用两个功能 |
| **期初持仓 = 一条买入记录**（采用） | 底层仍是 `purchase_lots` 的一行，所以持仓成本、止盈止损、分批计划全部照常工作 |

具体改动：

- `purchase_lots` 新增 `is_opening INTEGER NOT NULL DEFAULT 0`，老库由 `_migrate_columns()`
  自动 `ALTER TABLE` 补列（迁移可重复执行）；
- 录入表单（`LotFormDialog` 的 `mode="opening"`）**只问三件事**：品种、持有克数、平均成本价
  （+ 大致日期）。手续费 / 渠道 / 所属计划 / 备注全部隐藏 —— 那些是逐笔买入才需要的信息；
- **期初持仓不触发买入回访**：那不是一次需要跟进的买入，否则用户一录入持仓就被回访；
- 期初持仓**不顶替任何计划的批次**：它 `plan_id` 为空，`compute_plan_progress` 天然按
  `plan_id` 匹配，无需改判断逻辑。

前端在**建议配置页顶部**加了「我的当前持仓」卡片：没持仓时直接给出「录入我的持仓」按钮与
说明，有持仓时显示克数 / 成本价 / 浮动盈亏，并提供入口去「我的持仓」页编辑明细。
用户不用再猜持仓该去哪填。

### 19.3 风险偏好真的控制阈值与买卖比例

新增 `service/advice/risk.py`，把「保守 / 均衡 / 进取」三个词翻译成数字，
**所有倍率集中在一张表里**：

| | 止盈 | 浮亏提醒 | 止损 | 单次买入 | 止损力度 | 止盈卖出 |
|---|---|---|---|---|---|---|
| 保守 | +5% | -2% | -6% | 0.6× | 1.2× | 1.2× |
| 均衡 | +8% | -3% | -10% | 1.0× | 1.0× | 1.0× |
| 进取 | +12% | -5% | -15% | 1.4× | 0.8× | 0.8× |

保守档「更早止损、且减得更多」是有意的：风险承受能力低的人，亏损扩大比卖早更难受。

配套改动：

- `AdviceContext.risk` / `.position_ratio_limit` 两个只读属性作为唯一取值口；
- `signals.py` 顶部**删掉**了 `DEEP_LOSS_PCT` / `LOSS_PCT` / `PROFIT_PCT` /
  `POSITION_RATIO_HIGH_PCT` 四个常量，改读 `ctx.risk.*` 与 `ctx.position_ratio_limit`；
- `common.suggest_buy_grams` / `suggest_sell_grams` 内部按档位缩放，并**封顶在 1**
  （进取档 0.5×1.4=0.7 没问题，但不能超过剩余额度或持仓量）；
- 未知档位一律回落到均衡、不抛异常 —— 配置脏数据不该让建议生成失败；
- 信号与理由里写明档位（「已超过 -6% 阈值（保守档）」），否则用户不知道为什么 -7% 就报止损。

### 19.4 实测

固定行情 ¥954/克，期初持仓 30g @ ¥900（浮盈 +6%），总资金 ¥50000：

```
1) 录入当前持仓（只有克数 + 均价）→ is_opening=True
   持仓汇总：30.0g，成本价 ¥900.0，浮动 +6.00%
2) 待回访：[]                      ← 期初持仓不触发买入回访
3) 持仓市值 ¥28620 / ¥50000 = 57.2%
   目标占比未设（默认上限 100%）：position_ratio_high = False
   目标占比设为 50%：position_ratio_high = True
     提示语：持仓市值已占总可投资金的 57%，达到你设定的 50% 上限
4) 浮盈 +6%：
   conservative → TAKE_PROFIT  建议 12.0g
   balanced     → HOLD
   aggressive   → HOLD
   理由：……浮盈已达到 5% 阈值（保守档），建议分批锁定收益，
        先卖出约 12.0g（持仓的 40%），剩余继续持有
```

第 3、4 项在改动前**完全不会发生**。

### 19.5 验证方式

```bash
cd backend
python -m test.test_advice_risk          # 19 项（新增）
python -m test.test_advice               # 51 项（回归）
python -m test.test_review_followup      # 26 项（回归）
python -m test.test_review_scheduling     # 17 项（回归）
python -m test.test_entry_strategy       # 29 项（回归）
python -m test.test_portfolio            # 28 项（回归）
python -m test.test_monitor_send_gate    # 13 项（回归）
python -m test.test_market_session       # 14 项（回归）
python -m test.test_sqlite_connections   #  3 项（回归）
```

共 **207 项全部通过**。前端 `vue-tsc` / `eslint` / `prettier --check` 均通过。

### 19.6 还没做：卖出记账

用户已确认要补，并选定了**移动平均**口径（卖出按当前均价结转，剩余持仓成本价不变；
实现盈亏 =（卖价 − 均价）× 克数 —— 与现有「成本价 = 总投入 / 总克数」一致，界面不用改）。

在此之前，系统会建议「止盈卖出 12g」但**没地方记录**，持仓会一直偏大，
后续所有建议都建立在偏大的持仓上。这是下一轮的事。

---

## 20. 实施记录（卖出记账与移动平均结转）

记录日期：2026-10-03。**止盈/止损建议现在可以落地了** —— §19.6 那个缺口补上了。

### 20.1 口径（用户已确认：移动平均）

卖出按**当时**的持仓均价结转，剩余持仓的**成本价不变**：

```
已实现盈亏 = (卖价 − 卖出当时的均价) × 卖出克数
```

数学上 `(cost − avg×s) / (grams − s) = avg`，所以卖出一部分不会改变成本价。

**关键坑：均价会随买入变化，所以已实现盈亏必须按账本顺序逐笔推导。**
拿最终的均价乘总卖出量是错的，而且不会报错 —— 只会安静地给出一个错数字。
测试里专门锁了这个算例：

```
买 10g @900 → 卖 10g @1000（此时均价 900，已实现 +1000）→ 再买 10g @1000
正确：+1000（按卖出当时的 900）
错误：+500 （按最终均价 950）
```

手续费沿用「只记录、不摊入成本」的口径，**不冲减已实现盈亏**（即报税前数），
`total_fee`（买入）与 `sale_fee`（卖出）分开返回。

### 20.2 账本

`service/position.py` 从「求和」改成**按时间走一遍账本**：

- `build_ledger(lots, sales)` 把买入与卖出合并排序，**同一天买入排在卖出之前**
  （当天先买后卖是自然读法，也避免「今天买、今天卖」被判成超卖）；
- `walk_ledger(events)` 逐笔结转，产出剩余克数/成本、逐笔已实现盈亏；
- 超卖时**不把克数扣成负数**，只结转真正持有的部分，把超出量记在 `oversold_grams`
  —— 静默算出负持仓会让后面所有数字都不可信。

`compute_position` 的 `sales` 做成**仅关键字参数**：它是在 `latest_price` 之后才加的，
做成位置参数会把老调用里第三个位置上的价格当成卖出记录（`test_portfolio.py` 就有
这种位置调用），静默算错。

### 20.3 超卖守卫：先校验再落库

账本一旦出现「卖出多于持仓」，后面的成本价与已实现盈亏全都失真。所以在
**写入之前**用「改动之后的样子」预演一遍账本：

| 操作 | 为什么要校验 |
|---|---|
| 新增/修改卖出 | 卖出量可能超过持仓 |
| **改小**一笔买入 | 已有的卖出可能就超了 |
| 删除一笔买入 | 同上 |
| 删除卖出 | 不需要 —— 只会让持仓变多 |

刻意**先校验再落库**，而不是写完再回滚：回滚要按原 id 重新插回一行，
稍有不慎就会把 id 弄丢（进而让 `plan_id` 之类的引用悬空）。

### 20.4 实测（闭环）

期初持仓 30g @ ¥900，现价 ¥990（+10%），均衡档：

```
1) 引擎给出建议：TAKE_PROFIT，卖出 10.0g（30 × 1/3）
2) 记录这笔卖出：10g @ ¥990，该笔已实现 ¥900
3) 持仓与盈亏随之更新：20.0g，成本价仍 ¥900（移动平均）
   浮动 ¥1800，已实现 ¥900
4) 下一次建议：evidence.position.total_grams = 20.0，realized_pnl = 900
   建议卖出 6.6667g ← 按 20g 重算，不再是 10g
5) 卖出 999g → 400「卖出总量超出持仓 979g，请检查卖出记录…」
6) 删掉被依赖的买入 → 400「卖出总量超出持仓 10g，…」
```

第 4 步是闭环的证据：建议的克数从 10g 变成 6.67g，说明引擎**看到的是卖出后的持仓**。
（价格仍在 +8% 止盈线之上，所以继续分批止盈是正确行为，不是没生效。）

### 20.5 顺手修掉的一个真 bug

端到端跑的时候发现 `DELETE /portfolio/lots/{id}` **没有接 `ValueError`**：
超卖守卫抛出的异常会变成 500，前端只看到「服务器错误」，用户根本不知道自己做错了什么。
已改为 400 + 原因，并补了回归测试。

> 这个 bug 只有把接口层真正跑一遍才会暴露 —— 单元测试直接调 service，
> 看到的只是「异常抛对了」。

### 20.6 前端

- `SaleFormDialog.vue`：记一笔卖出（克数/单价/日期/手续费/渠道），带「最多可卖 Xg」
  与「全部卖出」；填总金额也能反推单价；
- 「我的持仓」页：新增**卖出记录**表（每笔带已实现盈亏）与「记一笔卖出」按钮；
- 持仓总览多一张**已实现盈亏**卡（没卖过就不显示，避免用「¥0.00」占位置）；
- **建议卡上直接给「记录这笔卖出」按钮**：动作是止盈/止损时出现，
  自动带上建议克数、建议价位中间价与当前可卖克数 —— 这就是「让建议落地」的那一步。

### 20.7 验证方式

```bash
cd backend
python -m test.test_sales               # 25 项（新增）
python -m test.test_advice              # 51 项（回归）
python -m test.test_advice_risk         # 19 项（回归）
python -m test.test_portfolio           # 28 项（回归）
python -m test.test_review_followup     # 26 项（回归）
python -m test.test_review_scheduling   # 17 项（回归）
python -m test.test_entry_strategy      # 29 项（回归）
python -m test.test_monitor_send_gate   # 13 项（回归）
python -m test.test_market_session      # 14 项（回归）
python -m test.test_sqlite_connections  #  3 项（回归）
```

共 **235 项全部通过**。前端 `vue-tsc` / `eslint` / `prettier --check` 均通过。
接口路径从 60 条增至 62 条（新增 `/api/portfolio/sales` 的增删改查中的 4 条，含列表）。

### 20.8 现在的完整闭环

```
记「我持有多少」（期初持仓，只填克数 + 均价）
  → 建议：买什么 / 买多少 / 一次买还是分批
  → 建议：持有 / 补仓 / 止盈 / 止损（基于你的真实成本）
  → 一键把建议的卖出记成流水（超卖会被拦住）
  → 持仓与已实现盈亏立刻反映，下一次建议基于新持仓
  → T+1/T+7/T+30 自动回访「这笔买得怎么样」
  → 回访价格自动回填 →「我的建议准不准」有据可查
```

---

## 21. 实施记录（工具链：uv 依赖拆分 + mypy / ruff 门禁）

记录日期：2026-10-03。起因是「用 uv 和 mypy 检查一下代码」，检查过程中发现
**若干真问题**（见 §21.4），于是把工具链固化下来，避免下次还得靠临时命令。

### 21.1 uv：运行依赖与开发依赖分开

`backend/pyproject.toml` 原来只有一个 `[project].dependencies`，没有开发依赖也没有
任何工具配置。按 uv 现在的标准（PEP 735 依赖组）拆成：

| 位置 | 内容 | 说明 |
|---|---|---|
| `[project].dependencies` | fastapi / uvicorn / requests / bs4 / lxml / chinese-calendar / python-dotenv | **运行**依赖，按用途分组加注释 |
| `[dependency-groups].dev` | mypy / ruff | **开发**依赖，不参与运行；用 `uv add --dev` 维护 |
| `[tool.uv] package = false` | —— | 这是**应用**不是库：不把自身构建/安装。当前无 `[build-system]`，uv 已推断为 virtual，显式写出来是为了以后有人加了构建后端时行为不会突变 |

锁定后 `uv.lock` 从 29 个包变成 35 个（多了 mypy、ruff 及其依赖）。

> 索引镜像（清华源）配在**全局** `%APPDATA%\uv\uv.toml` 里，不在项目内 ——
> 所以 `[tool.uv]` 没有、也不应该重复声明 index，否则会覆盖全局设置。

### 21.2 mypy：只把生产代码纳入门槛

```toml
[tool.mypy]
python_version = "3.13"
files = ["."]
exclude = ['^\.venv/', '^test/']
disable_error_code = ["prop-decorator"]
```

- **排除 `test/`**：测试里有大量替身（`FakeSettings` / `FakePriceMapper` …）赋给具体类型的
  属性、以及直接索引 `Optional` 返回值，共 95 条。先把生产代码管住，测试逐步收紧。
- **`disable_error_code = ["prop-decorator"]`**：Pydantic 的 `@computed_field` 叠在
  `@property` 上会被 mypy 误报，属框架层面的已知不兼容，不是我们的问题。

结果：`uv run mypy` → **Success: no issues found in 85 source files**（exit 0）。

### 21.3 ruff：显式规则集，且当前零告警

```toml
[tool.ruff]
target-version = "py313"

[tool.ruff.lint]
select = ["E4", "E7", "E9", "F", "I", "UP", "B", "C4", "DTZ"]
ignore = ["UP042"]

[tool.ruff.lint.per-file-ignores]
"test/*" = ["DTZ001", "DTZ005", "DTZ007"]
```

三个刻意的选择：

1. **显式 `select`**：ruff 0.16 的内置默认比经典的 `E4/E7/E9/F` 宽得多（会报 DTZ / RUF / I），
   显式声明才能让「本地检查」和「CI 检查」看到同一套规则。
2. **`DTZ`**：这一族规则**真的抓到过 bug** —— §19 里 `context.py` 的
   `advised_at` 用了裸 `datetime.now()`，绕过项目统一的 `now()`。同类问题靠人眼很容易漏。
3. **`ignore = ["UP042"]` 是有意的**，不是图省事：它建议把
   `class AdviceKind(str, Enum)` 换成 `enum.StrEnum`，而 `StrEnum` 会改变
   `str(member)` 的结果（`"AdviceAction.BUY_NOW"` → `"BUY_NOW"`）。
   `monitor_service` 里既有**直接插进日志**的地方（`:175`），也用它**拼去重键**（`:189`）——
   那属于行为变更，不该混在一次 lint 修复里。要改需单独评估。

配套修掉的 7 处（让门禁真的能过，而不是加一个必然失败的配置）：

| 位置 | 问题 |
|---|---|
| `app.py` / `test_monitor_send_gate.py` | import 顺序 |
| `test_advice_notification.py` / `test_portfolio.py` | 未使用的 import |
| `service/log_service.py` | `open(p, "r")` → `open(p)` |
| `mapper/price_mapper.py` | 两处 `zip()` 加 `strict=True` —— 两个序列都由 `prices_with_time` 推出、长度必须一致；万一以后只改一边，会直接报错而不是悄悄截断少算 |
| `models/portfolio.py` | `_validate_trade_date` 只校验格式、不做时区运算，给 `strptime` 加 `# noqa: DTZ007` 并说明原因 |

结果：`uv run ruff check` → **All checks passed!**（exit 0）。

### 21.4 这次检查找出的真问题

| # | 问题 | 性质 |
|---|---|---|
| 1 | `service/advice/context.py` 用裸 `datetime.now()` 写 `advised_at`，绕过项目统一的 `now()`；且 `AdviceContext.at` 从未被赋值，永远走 fallback | **时区 bug**，非 +08:00 机器上记录的时间是错的 |
| 2 | `DELETE /portfolio/lots/{id}` 不接 `ValueError`，超卖守卫变成 500 | **接口层 bug**，用户只看到「服务器错误」 |
| 3 | `AdviceSettings.vue` 用 `positions[0]` 判断有无持仓，而全部卖光的品种也在列表里 → 会谎称「还没有录入持仓」 | **前端 bug** |
| 4 | 三个策略文件用 `base = dict(...)` + `AdviceDraft(**base)`，mypy 为每个字段各报一条（共 113 条） | **类型检查被绕过** —— 整个策略层（决定买卖与数量）等于没检查。改用 `TypedDict` 修掉 |
| 5 | `system_settings_mapper.py` 5 处 `if own:` 让 mypy 无法收窄（15 条误报） | 改为 `if conn is None:`，行为不变 |

### 21.5 验证方式

```bash
cd backend
uv run mypy                       # Success: no issues found in 85 source files
uv run ruff check                 # All checks passed!
uv lock --check                   # 锁文件与 pyproject 一致
uv run python -m test.test_sales  # 235 项测试全部通过
```

顺手在根 `.gitignore` 补了 `.mypy_cache/`、`.ruff_cache/`、`.pytest_cache/`、
`.uv-cache/` —— 加了 dev 依赖之后，跑一次工具就会在 `backend/` 下生成这些缓存目录。

### 21.6 还没做

- **把 mypy 收紧到 `test/`**：需要先给测试替身加 Protocol 或改用 `cast`，属于独立工作。
- **`uv run ruff format --check`**：格式化目前交给编辑器（`.vscode/settings.json` 指定
  Ruff 为 formatter + 保存时修复）。要当门禁得先跑一遍全量格式化，会产生较大 diff，
  建议单独一次提交。

---

## 22. 实施记录（LLM 提示词同步）

记录日期：2026-10-03。起因是「发给 LLM 的提示词需要同步修改优化吗」——
一路改下来（风险偏好、建仓回测、复盘、卖出、期初持仓），提示词确实已经跟不上了。

### 22.1 四条提示词与实现脱节的地方

| 问题 | 证据 |
|---|---|
| **长度上限容不下规则理由** | 购买前（含建仓回测）的规则理由 **188 字**，而 system prompt 写的是「不超过 180 字」。模型必须压缩，最可能删掉的正是回测证据 —— 而那是这条建议唯一的量化依据 |
| **提示词不含建议类型** | `draft.kind` 从未进入提示词。复盘建议（「回访你在 2026-01-13 买入的 10g」）可能被改写成一条**全新的买卖建议**，丢掉复盘的全部意义 |
| **提示词不含已实现盈亏** | 用户已卖 10g、落袋 +¥1000，但提示词只写「持仓 20g，浮动 +¥1800」—— 模型不知道他已经止盈过，也无法解释「为什么现在只减 8g」 |
| **缺失行情被写成了 0** | `f"浮动盈亏 ¥{position.unrealized_pnl or 0:.2f}"` —— `None or 0` 把「不知道」变成「持平 0%」，而提示词又要求模型「必须提及关键数字」，等于让它复述一个假数字。这一条与项目自己的原则（拿不到行情返回 `None` 而不是 0）直接冲突 |

### 22.2 改法

`advisor.py`：

- 结论区新增 **`建议类型`**，并新增 `KIND_GUIDANCE`：四类建议各给一条写作要求。
  复盘那条明确要求「必须保留『回访你在 <日期> 买入的 <克数>』这一指代，
  不要让读者以为这是一条全新的买卖建议」
- 【持仓】区在有卖出时补 **`已卖出 Xg（N 笔），已实现盈亏 ¥Y（不含手续费）`**；
  全部卖光时写「当前已清仓」而不是「没有持仓」，否则已实现盈亏会被藏掉
- 新增 **【风险偏好】** 区，写明档位与三个阈值（止盈 / 浮亏提醒 / 止损）——
  否则模型解释不清「为什么 +5% 就提示止盈」
- `RATIONALE_MAX_CHARS = 220`（原 180），并把这个数字写进 system prompt。
  选 220 是因为最长的规则理由是 188 字
- 缺失行情改标 **「无行情」**，不再退化成 0；system prompt 同时加一句
  「标注为『无行情』的字段表示系统拿不到该数据，**不要猜测它的数值**」

### 22.3 为什么保留 system + user 的结构

曾考虑「合并成一个 user prompt 会不会更好」，结论是**不合并**：

- **system prompt 确实送达了**。模型池只有一处构造 payload
  （`model_pool_engine._call_single`），`{"role": "system"}` + `{"role": "user"}`，
  所有供应商都是 OpenAI 兼容格式，不存在适配器丢掉 system role 的情况。
- **契约与数据的生命周期不同**。system 里放的是**跨四类建议都不变**的东西
  （不得改数字、只输出 JSON、长度上限），user 里是每条建议各自的行情/持仓/信号。
  合并意味着契约文字每次调用都要重新拼一遍，更容易漂移。
- 参数也合适：`temperature = 0.3`（低随机）、`max_tokens = 4096`（远大于 220 字）。

但「指令位置」的担心是真实的，于是做了两处改动：

**1. 关键约束在 user prompt 末尾重申。** 那两条最不能违反的要求原本距落笔位置有
40 多行，而模型池是**多供应商故障转移**的 —— 换一个模型时对 system role 的遵守
程度未必一致。末尾加一段：

```
【输出要求（重申）】
- 只输出 JSON，不要任何其他内容：{"rationale": "改写后的理由"}
- 不超过 220 字
- 不得修改、重新计算或编造任何数字
```

**2. 缓存键纳入 system prompt。** 原来是 `sha1(user_prompt)` —— 只改 system prompt
时缓存键不变，**在 60 分钟 TTL 内会继续命中用旧约束生成的措辞**。改为
`sha1(system_prompt + "\0" + user_prompt)`。这也部分回答了下面 §22.5 的版本化问题。

### 22.4 顺带清掉的死提示词

`AIAnalysisService.analyze()` 及其 6 个辅助方法（`_price_bucket` / `_cache_key` /
`_build_prompt` / `_trend_desc` / `_parse_response`）与它专用的 `SYSTEM_PROMPT`
**完全没有调用方** —— §18 清理报警路径时漏掉了这一整块。而且那个提示词的内容是：

> 系统已触发价格报警条件（见下方【触发条件】），请你结合市场数据判断是否值得向投资者发送通知

与现在的产品（不再有报警、也不再让 LLM 决定发不发）完全相反。留着它比没有更糟：
任何人打开 `ai_service.py` 都会以为 AI 还在做「该不该发通知」的判断。

`backend/service/ai_service.py` 从 **327 行删到 110 行**，只保留仍在用的
`complete()` / `_log_token_usage()` / `_ensure_model_pool()` 等。措辞层与行情分析层
仍共用同一套模型池。

### 22.5 验证方式

```bash
cd backend
python -m test.test_advice_prompt     # 21 项（新增）
uv run mypy                           # Success: no issues found in 85 source files
uv run ruff check                     # All checks passed!
```

共 **256 项测试全部通过**。新增的 `test_advice_prompt.py` 把这几条硬要求固定下来，
避免以后再改建议类型或卖出逻辑时又忘记同步提示词：

- 提示词必须含 `建议类型：<kind>`，且每个 `AdviceKind` 都有对应的写作要求
- 有卖出时必须含已实现盈亏；没卖过时不得出现
- 必须含风险偏好档位与具体阈值，且随档位变化
- 缺失行情必须标「无行情」，且**不得**出现 `¥0.00` / `+0.00%`
- 最长的规则理由必须 ≤ `RATIONALE_MAX_CHARS`
- 两条硬约束必须在 **user prompt 的最后一段**重申（不只是存在）
- 改 system prompt 必须换缓存键；相同输入必须得到相同缓存键
- 旧报警提示词与 `should_alert` 已从服务层消失

### 22.6 还没做

- **提示词版本落库**：缓存键现在覆盖了 system prompt，但建议记录里仍没有
  「这条措辞是哪版提示词生成的」。若要事后对比措辞质量，需要把提示词摘要写进
  `evidence`。
