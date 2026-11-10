# 压测与验证脚本

隔离方式：**以本目录为工作目录运行**，`config.py` 里的相对路径
（`data/prices.db` 等）会全部解析到 `./data/`，不会碰项目真实的 `backend/data/`。

## 用法

```bash
# 1. 造数（默认 365 天 × 10s × 2 品种 ≈ 630 万行 / 840MB，约 45s）
python build_data.py
# 可调：PERF_DAYS / PERF_INTERVAL / PERF_ADVICE / PERF_NOTIFY / PERF_AI

# 2. 进程内基准（真实 service + mapper，网络与 LLM 打桩）
python bench_inproc.py

# 3. 起服务 + HTTP 压测
python server.py                 # 默认 8765，可用 PERF_PORT 覆盖
python loadtest.py 8765          # 单接口基线 + 并发梯度 + 混合场景

# 4. 读写争用（监控线程写入是否拖慢读）
python contention.py 8765

# 5. 大规模一致性验证（日线聚合 vs 原始表）
python verify_consistency.py
```

## 各脚本职责

| 文件 | 作用 |
|---|---|
| `build_data.py` | 生成压测数据集（价格 tick / 建议 / 通知日志 / AI 日志 / 持仓） |
| `bench_inproc.py` | 直接调 service 与 mapper，量出每个函数的纯 DB+CPU 开销 |
| `server.py` | 以本目录为 cwd 启动 uvicorn，用 mock 库跑真实 HTTP 路径 |
| `loadtest.py` | HTTP 单接口基线、并发梯度、按前端真实比例的混合场景 |
| `writer.py` | 模拟监控线程写库（独立进程，用于读写争用测试） |
| `contention.py` | 有无并发写入时读延迟的对比 |
| `probe_misc2.py` | 定向实验：索引形状对比、连接策略、并发扩展性 |
| `verify_consistency.py` | 630 万行上核对日线聚合与原始表逐项一致 |

## 注意

- 造数脚本产出的数据必须满足 Pydantic 模型的枚举与必填约束
  （如 `purchase_plans.status` 只能是 `active/cancelled/done/paused`，
  `advice_records.signals` 的每一项必须带 `summary`），否则接口会返回 500 ——
  那是造数问题，不是服务端缺陷。
- `verify_consistency.py` 里「首桶」允许 0.05 的偏差：区间起点落在某天中间时，
  逐 tick 实现只统计残日、日线表用整天，属预期口径差异。
- 跑完记得删除 `data/`（几百 MB）。

## PostgreSQL 对比（pg_*.py）

用嵌入式 PostgreSQL 实测「换库能带来什么」，不改动系统环境。

```bash
# 需要 Python 3.12（pgserver 只提供到 cp312 的 wheel）+ 独立 venv
uv venv --python 3.12 .venvpg
uv pip install --python .venvpg/Scripts/python.exe pgserver "psycopg[binary]"

# 先按上面的步骤 1 造好 SQLite 数据集，然后：
.venvpg/Scripts/python.exe pg_bench.py    # 启动 PG → COPY 导入 → 逐查询对比
.venvpg/Scripts/python.exe pg_vacuum.py   # 补测 VACUUM 对 index-only scan 的影响
.venvpg/Scripts/python.exe pg_extra2.py   # INCLUDE 覆盖索引后的公平对比
```

要点：
- PG 刚批量导入后**必须 `VACUUM`**，否则可见性映射未建立，index-only scan 不可用，
  规划器会退化成并行全表扫描（MIN 查询从 73ms 变 200ms）。
- 两边都要用**常驻连接**测纯查询时间；「每查询新建连接」要单独测
  （SQLite 1.95ms vs PG 26.9ms，这是迁移必须上连接池的原因）。
- 跑完删 `perf3/pgdata`，并确认没有残留 postgres 进程。

## 真实服务器实测（server/）

在 Ubuntu 服务器上装 PostgreSQL 18 并同机对比，脚本在 `server/`：

| 文件 | 作用 |
|---|---|
| `gen.py` | 生成 CSV + 日线聚合（只用标准库，无第三方依赖） |
| `build_db.py` | 从 CSV 构建 SQLite（schema/索引与 App 完全一致） |
| `load_pg.py` | 建 PG 表 + `COPY` 导入 + 建索引 + `ANALYZE` + `VACUUM` |
| `bench.py` | SQLite vs PG 逐查询对比（常驻连接，方法对称） |

在服务器上的执行顺序：

```bash
mkdir -p ~/work && cd ~/work        # 把 4 个脚本传上来
python3 gen.py                      # 生成 perfdata/（约 2 分钟 / 435MB CSV）
python3 build_db.py                 # 构建 perfdata/perf.db（550MB）
python3 load_pg.py                  # 导入 PG（需先建库：createdb perf -O $USER）
python3 bench.py                    # 输出对比表
```

服务器端准备：

```bash
sudo apt-get install -y postgresql postgresql-contrib python3-psycopg2
sudo -u postgres createuser --superuser "$USER"
sudo -u postgres createdb perf -O "$USER"
```

**关键坑（都踩过）**：
- `COPY ... WITH (FORMAT csv)` 下「未加引号的空字段」默认是 NULL；
  若该列 NOT NULL 会报错。用 `NULL '\N'` 让空字段保持空字符串。
  （另一方面，需要空→NULL 的列反而要用 `NULL ''`。）
- 导入后**必须 `VACUUM`**，否则可见性映射未建立，index-only scan 不可用。
- 测「小查询」时一定要用**常驻连接**，否则测到的是连接开销
  （Linux 上 SQLite 0.10ms vs PG 3.51ms；Windows 上是 1.95ms vs 26.9ms）。
