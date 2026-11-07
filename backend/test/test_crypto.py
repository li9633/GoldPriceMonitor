"""utils.crypto 加解密工具测试。"""
import os

import pytest

import utils.crypto as crypto


def test_encrypt_decrypt_roundtrip():
    cipher = crypto.encrypt_value("sk-my-secret-key")
    assert cipher.startswith("enc:")
    assert crypto.is_encrypted(cipher)
    assert crypto.decrypt_value(cipher) == "sk-my-secret-key"


def test_encrypt_empty_value_returns_empty():
    assert crypto.encrypt_value("") == ""
    assert crypto.decrypt_value("") == ""


def test_decrypt_plaintext_is_pass_through():
    # 历史明文数据应原样返回（兼容）
    assert crypto.decrypt_value("legacy-plaintext") == "legacy-plaintext"
    assert not crypto.is_encrypted("legacy-plaintext")


def test_is_key_configured():
    assert crypto.is_key_configured()


def test_encrypt_raises_without_key(monkeypatch):
    monkeypatch.delenv("GOLD_MONITOR_SECRET_KEY", raising=False)
    crypto._fernet_instance = None  # 清空缓存，强制重新读取环境变量
    assert not crypto.is_key_configured()
    with pytest.raises(RuntimeError, match="GOLD_MONITOR_SECRET_KEY"):
        crypto.encrypt_value("secret")
    monkeypatch.setenv(
        "GOLD_MONITOR_SECRET_KEY", os.environ.get("GOLD_MONITOR_SECRET_KEY", "")
    )
    crypto._fernet_instance = None
