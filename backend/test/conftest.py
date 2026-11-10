"""pytest 共享配置与夹具。

**测试隔离**：`test_sales.py` 会 `import app`，而 `app.py` 在模块级就
`import controller.*`，各控制器又是 `service = XxxService()` 模块级单例 ——
构造时会立刻对 `config` 里的数据库路径执行建表/建索引。

结果就是：**跑一次 pytest 会写到 `backend/data/` 里的真实开发库**。
真实库有数据时，`PriceMapper.init_table()` 还会触发日线表全量重建
（630 万行约 5 秒），既慢又改了开发数据。

因此这里在**导入任何 mapper 之前**把库路径整体重定向到临时目录。
conftest 的模块体会在所有测试模块之前执行，而各 mapper 用的是
`from config import XXX_DB_FILE` 的**导入期取值**，所以改 `config` 属性即可生效。
"""

import atexit
import os
import shutil
import tempfile

import pytest
from cryptography.fernet import Fernet

# 在收集测试前确保加密密钥环境变量已配置（用于敏感字段加密相关测试）
os.environ.setdefault("GOLD_MONITOR_SECRET_KEY", Fernet.generate_key().decode())

# ==================== 数据库路径重定向到临时目录 ====================

_TEST_ROOT = tempfile.mkdtemp(prefix="goldmon-test-")
_STATE = os.path.join(_TEST_ROOT, "data")
os.makedirs(_STATE, exist_ok=True)
atexit.register(shutil.rmtree, _TEST_ROOT, ignore_errors=True)

import config  # noqa: E402  —— 必须在任何 mapper 被导入之前改它

config.PRICE_HISTORY_DB_FILE = os.path.join(_STATE, "prices.db")
config.PORTFOLIO_DB_FILE = os.path.join(_STATE, "portfolio.db")
config.SYSTEM_SETTINGS_DB_FILE = os.path.join(_STATE, "system_settings.db")
config.MODEL_POOL_DB_FILE = os.path.join(_STATE, "model_pool.db")


@pytest.fixture
def tmp_db(tmp_path) -> str:
    """返回一个临时 SQLite 数据库文件路径。"""
    return str(tmp_path / "test.db")
