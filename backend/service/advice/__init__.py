"""建议域：规则出事实，LLM 只出表述。

模块划分见 `docs/refactor-plan.md` §8：

- `context.py` —— 行情指标 + 持仓 + 计划 + 偏好，并负责把行情快照序列化以便冻结
- `signals.py` —— 确定性信号（纯函数，可单测、可回测）
- `strategies/` —— 三套策略：购买前 / 购买后 / 计划执行
- `advisor.py` —— LLM 措辞层（只改说法，不改结论）
- `advice_engine.py` —— 编排与落库

本 `__init__` 刻意不导入任何子模块：避免 `import service.advice.signals` 这类
纯计算导入顺带实例化数据库连接。
"""
