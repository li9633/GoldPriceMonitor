"""敏感字段（邮箱密码 / LLM API Key）对称加密工具。

- LLM API Key / 邮箱密码：加密后存储在数据库，不使用环境变量。
- 加解密密钥本身：通过环境变量 GOLD_MONITOR_SECRET_KEY 提供（Fernet key）。
"""
import os
import threading

from cryptography.fernet import Fernet, InvalidToken

from config import SECRET_KEY_ENV
from utils.logger import get_logger

logger = get_logger("Crypto")

_PREFIX = "enc:"
_lock = threading.Lock()
_fernet_instance: Fernet | None = None

_MISSING_KEY_MSG = (
    f"未配置加密密钥环境变量 {SECRET_KEY_ENV}，无法加解密敏感字段。"
    "请先生成密钥：python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"，"
    f"然后设置环境变量 {SECRET_KEY_ENV}（Windows: set {SECRET_KEY_ENV}=xxx；Linux/Mac: export {SECRET_KEY_ENV}=xxx）。"
)


def _get_fernet() -> Fernet:
    """从环境变量加载密钥并缓存 Fernet 实例（进程内仅创建一次）。"""
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance
    with _lock:
        if _fernet_instance is not None:
            return _fernet_instance
        raw = os.getenv(SECRET_KEY_ENV, "").strip()
        if not raw:
            raise RuntimeError(_MISSING_KEY_MSG)
        _fernet_instance = Fernet(raw.encode("ascii"))
        return _fernet_instance


def is_key_configured() -> bool:
    """环境变量中的加密密钥是否已配置。"""
    return bool(os.getenv(SECRET_KEY_ENV, "").strip())


def encrypt_value(value: str) -> str:
    """加密字符串；空值原样返回，返回带前缀的密文。"""
    if not value:
        return value
    return _PREFIX + _get_fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_value(value: str) -> str:
    """解密字符串；空值、历史明文原样返回。"""
    if not value or not value.startswith(_PREFIX):
        return value
    try:
        return _get_fernet().decrypt(value[len(_PREFIX):].encode("ascii")).decode(
            "utf-8"
        )
    except (InvalidToken, ValueError) as e:
        logger.warning("敏感字段解密失败：%s", e)
        return value


def is_encrypted(value: str) -> bool:
    return bool(value) and value.startswith(_PREFIX)
