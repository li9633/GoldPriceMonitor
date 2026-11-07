"""service.model_pool_engine 工具函数与数据结构测试。"""
import json

from service.model_pool_engine import ModelPool, ModelResult, _describe_http_status


class TestDescribeHttpStatus:
    def test_known_codes(self):
        assert _describe_http_status(401) == "API Key 无效或未授权"
        assert _describe_http_status(429) == "请求频率超限（Rate Limit）"
        assert _describe_http_status(500) == "服务器内部错误"
        assert _describe_http_status(503) == "服务不可用（临时过载或维护中）"

    def test_unknown_code(self):
        assert _describe_http_status(999) == "未知 HTTP 错误"


class TestExtractTokens:
    def test_valid_usage(self):
        raw = json.dumps(
            {"usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}}
        )
        assert ModelPool._extract_tokens(raw) == (10, 20, 30)

    def test_none_response(self):
        assert ModelPool._extract_tokens(None) == (0, 0, 0)

    def test_invalid_json(self):
        assert ModelPool._extract_tokens("not-json") == (0, 0, 0)

    def test_missing_usage(self):
        assert ModelPool._extract_tokens('{"choices": []}') == (0, 0, 0)


class TestModelResult:
    def test_defaults(self):
        r = ModelResult(success=True)
        assert r.content is None
        assert r.provider is None
        assert r.from_cache is False
        assert r.retryable is True
        assert r.raw_response is None

    def test_failure_with_error(self):
        r = ModelResult(success=False, error="boom", retryable=False)
        assert r.error == "boom"
        assert r.retryable is False
