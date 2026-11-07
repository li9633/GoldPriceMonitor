"""pytest 共享配置与夹具。"""
import os

import pytest
from cryptography.fernet import Fernet

# 在收集测试前确保加密密钥环境变量已配置（用于敏感字段加密相关测试）
os.environ.setdefault("GOLD_MONITOR_SECRET_KEY", Fernet.generate_key().decode())


@pytest.fixture
def tmp_db(tmp_path) -> str:
    """返回一个临时 SQLite 数据库文件路径。"""
    return str(tmp_path / "test.db")
