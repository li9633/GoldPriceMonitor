"""models 响应包装与 Pydantic 模型测试。"""
from models.response import ApiResponse, PageResponse
from models.system_settings import (
    AlertConfigModel,
    EmailConfigModel,
    MonitorConfigModel,
)


class TestApiResponse:
    def test_ok(self):
        r = ApiResponse.ok({"a": 1})
        assert r.code == 200
        assert r.data == {"a": 1}

    def test_fail(self):
        r = ApiResponse.fail("出错了", code=500)
        assert r.code == 500
        assert r.message == "出错了"
        assert r.data is None

    def test_success(self):
        r = ApiResponse.success()
        assert r.code == 200
        assert r.data is None


class TestPageResponse:
    def test_of(self):
        r = PageResponse.of([1, 2, 3], total=10, page=1, page_size=5)
        assert r.items == [1, 2, 3]
        assert r.total_pages == 2

    def test_of_exact_page(self):
        r = PageResponse.of([1], total=5, page=1, page_size=5)
        assert r.total_pages == 1


class TestConfigModels:
    def test_alert_config_defaults(self):
        m = AlertConfigModel()
        assert m.absolute_low_price == 915.0
        assert m.enable_absolute_alert is True

    def test_email_config_defaults(self):
        m = EmailConfigModel()
        assert m.smtp_server == "smtp.qq.com"
        assert m.smtp_port == 587
        assert m.sender_password == ""

    def test_monitor_config_json_fields(self):
        m = MonitorConfigModel()
        assert isinstance(m.monitor_symbols, list)
        assert "gds_AUTD" in m.monitor_symbols
        assert isinstance(m.trading_hours, list)
