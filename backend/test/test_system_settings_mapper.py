"""mapper.system_settings_mapper 白名单校验与敏感字段加密落库测试。"""
import json
import sqlite3

import pytest

from mapper.system_settings_mapper import (
    SystemSettingsMapper,
    _validate_columns,
    _validate_table,
)


class TestValidation:
    def test_validate_table_ok(self):
        _validate_table("alert_config")

    def test_validate_table_invalid(self):
        with pytest.raises(ValueError):
            _validate_table("evil; DROP TABLE")

    def test_validate_columns_ok(self):
        _validate_columns(["name", "api_url", "sender_password"])

    def test_validate_columns_invalid(self):
        with pytest.raises(ValueError):
            _validate_columns(["name; DROP TABLE"])


class TestEmailPasswordEncryption:
    def test_password_encrypted_at_rest(self, tmp_db):
        sm = SystemSettingsMapper(tmp_db)
        sm.init_tables()
        sm.upsert_notification_channel(
            "email", "邮件", True, 10, {"sender_password": "smtp-secret-123"}
        )
        # 读取时解密还原
        channels = sm.get_notification_channels()
        email = next(c for c in channels if c["channel_type"] == "email")
        assert email["config"]["sender_password"] == "smtp-secret-123"
        # 数据库中的落库值是密文
        conn = sqlite3.connect(tmp_db)
        raw = conn.execute(
            "SELECT config FROM notification_channels WHERE channel_type='email'"
        ).fetchone()[0]
        conn.close()
        assert json.loads(raw)["sender_password"].startswith("enc:")

    def test_empty_password_not_encrypted(self, tmp_db):
        sm = SystemSettingsMapper(tmp_db)
        sm.init_tables()
        sm.upsert_notification_channel(
            "email", "邮件", True, 10, {"sender_password": ""}
        )
        conn = sqlite3.connect(tmp_db)
        raw = conn.execute(
            "SELECT config FROM notification_channels WHERE channel_type='email'"
        ).fetchone()[0]
        conn.close()
        assert json.loads(raw)["sender_password"] == ""
