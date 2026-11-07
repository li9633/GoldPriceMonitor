"""channels 通知渠道测试：错误分类与配置校验。"""
from channels.base import classify_error
from channels.email_channel import EmailChannel
from channels.wechat_channel import WechatWorkChannel


class TestClassifyError:
    def test_empty(self):
        assert classify_error("") == ""

    def test_network_timeout(self):
        assert classify_error("connection timed out") == "network_timeout"
        assert classify_error("connect failed") == "network_timeout"

    def test_auth_failed(self):
        assert classify_error("535 auth error") == "auth_failed"
        assert classify_error("401 Unauthorized") == "auth_failed"

    def test_config_missing(self):
        assert classify_error("webhook_url 未配置") == "config_missing"
        assert classify_error("not configured") == "config_missing"

    def test_rate_limited(self):
        assert classify_error("rate limit exceeded") == "rate_limited"
        # 企业微信频率限制错误码 45009 应优先匹配 rate_limited
        assert classify_error("errcode=45009") == "rate_limited"

    def test_api_error(self):
        assert classify_error("errcode=40001") == "api_error"
        assert classify_error("status_code=500") == "api_error"

    def test_unknown(self):
        assert classify_error("something weird") == "unknown"


class TestEmailChannel:
    def test_validate_config_complete(self):
        cfg = {
            "smtp_server": "smtp.qq.com",
            "sender_email": "a@qq.com",
            "sender_password": "pass",
            "receiver_email": "b@qq.com",
        }
        assert EmailChannel().validate_config(cfg) is True

    def test_validate_config_missing_field(self):
        cfg = {"smtp_server": "smtp.qq.com", "sender_email": "a@qq.com"}
        assert EmailChannel().validate_config(cfg) is False


class TestWechatChannel:
    def test_validate_config_with_webhook(self):
        cfg = {"enabled": True, "webhook_url": "https://qyapi.weixin.qq.com/xxx"}
        assert WechatWorkChannel().validate_config(cfg) is True

    def test_validate_config_disabled(self):
        cfg = {"enabled": False, "webhook_url": "https://qyapi.weixin.qq.com/xxx"}
        assert WechatWorkChannel().validate_config(cfg) is False

    def test_validate_config_missing_url(self):
        cfg = {"enabled": True, "webhook_url": ""}
        assert WechatWorkChannel().validate_config(cfg) is False
