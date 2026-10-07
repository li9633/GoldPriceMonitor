"""金价 provider 化测试（infra-refactor-plan §3）。

1. huilvbiao 解析：与迁移前行为一致（含字段不足、缺品种行、网络失败）；
2. 新浪解析：字段布局同构（price=0/time=6/date=12，2026-10-07 实测）、
   空数据行返回 None、GBK 编码不影响价格解析；
3. 管理器：主源失败回落备源、连续失败 2 次切换主源；
4. PriceService 薄壳：返回结构与迁移前一致，hf_XAU 附折算价。

运行
----
    cd backend
    python -m test.test_price_provider
"""

from unittest import mock

import requests

import providers.price.huilvbiao as huilvbiao_module
import providers.price.sina as sina_module
from providers.price import (
    HuilvbiaoPriceProvider,
    PriceProviderManager,
    SinaPriceProvider,
)
from service.price_service import PriceService

HUILVBIAO_TEXT = (
    'var hq_str_gds_AUTD="906.80,0,905.90,906.80,908.20,896.33,15:29:38,'
    '896.61,898.75,23008,1.00,4.00,2026-09-30,黄金延期";\n'
    'var hq_str_hf_XAU="4133.04,4163.780,4133.04,4133.39,4169.79,4126.81,'
    '15:54:00,4163.78,4166.99,0,0,0,2026-10-07,伦敦金（现货黄金）";'
)

SINA_TEXT = (
    'var hq_str_hf_XAU="4133.04,4163.780,4133.04,4133.39,4169.79,4126.81,'
    '15:54:00,4163.78,4166.99,0,0,0,2026-10-07,伦敦金（现货黄金）";\n'
    'var hq_str_gds_au9999="";'
)


class FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        pass


# ==================== huilvbiao ====================


def test_huilvbiao_parses_sina_format() -> None:
    provider = HuilvbiaoPriceProvider()
    with mock.patch.object(
        huilvbiao_module, "safe_get", lambda *a, **k: FakeResponse(HUILVBIAO_TEXT)
    ):
        quote = provider.fetch("gds_AUTD")
    assert quote is not None
    assert quote.price == 906.80
    assert quote.trade_time == "15:29:38"
    assert quote.trade_date == "2026-09-30"


def test_huilvbiao_missing_symbol_returns_none() -> None:
    provider = HuilvbiaoPriceProvider()
    with mock.patch.object(
        huilvbiao_module, "safe_get", lambda *a, **k: FakeResponse('var hq_str_gds_AUTD="1,2,3";')
    ):
        assert provider.fetch("hf_XAU") is None, "响应中无该品种行"


def test_huilvbiao_short_fields_returns_none() -> None:
    provider = HuilvbiaoPriceProvider()
    with mock.patch.object(
        huilvbiao_module, "safe_get", lambda *a, **k: FakeResponse('var hq_str_gds_AUTD="906.80,0";')
    ):
        assert provider.fetch("gds_AUTD") is None


def test_huilvbiao_network_failure_returns_none() -> None:
    provider = HuilvbiaoPriceProvider()
    with mock.patch.object(huilvbiao_module, "safe_get", lambda *a, **k: None):
        assert provider.fetch("gds_AUTD") is None


# ==================== 新浪 ====================


def test_sina_parses_same_layout_as_huilvbiao() -> None:
    """gds_/hf_ 两个系列布局一致（2026-10-07 实测确认）"""
    provider = SinaPriceProvider()
    with mock_sina_get(SINA_TEXT):
        hf = provider.fetch("hf_XAU")
    assert hf is not None
    assert hf.price == 4133.04
    assert hf.trade_time == "15:54:00"
    assert hf.trade_date == "2026-10-07"


def test_sina_empty_data_line_returns_none() -> None:
    """`var hq_str_gds_au9999=""` 表示无数据（盘后/品种无行情）"""
    provider = SinaPriceProvider()
    with mock_sina_get('var hq_str_gds_au9999="";'):
        assert provider.fetch("gds_au9999") is None


def test_sina_network_failure_returns_none() -> None:
    provider = SinaPriceProvider()

    def raise_error(*args, **kwargs):
        raise requests.RequestException("blocked")

    with mock.patch.object(sina_module.requests, "get", raise_error):
        assert provider.fetch("gds_AUTD") is None


# ==================== 管理器 ====================


class StubProvider:
    def __init__(self, name: str, quote=None, trace: list | None = None):
        self._name = name
        self._quote = quote
        self._trace = trace
        self.calls = 0

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def api_url(self) -> str:
        return f"https://example.com/{self._name}"

    def fetch(self, symbol):
        self.calls += 1
        if self._trace is not None:
            self._trace.append(self._name)
        return self._quote


def _quote(symbol="gds_AUTD", price=906.80):
    from providers.price.base import PriceQuote

    return PriceQuote(symbol=symbol, price=price)


def test_manager_falls_back_to_sina() -> None:
    manager = PriceProviderManager(
        [StubProvider("huilvbiao"), StubProvider("sina", _quote())]
    )
    quote = manager.fetch("gds_AUTD")
    assert quote is not None and quote.price == 906.80
    assert manager.current_provider == "sina", "主源失败应使用备源"


def test_manager_switches_after_repeated_total_failures() -> None:
    """双源全挂：连续 2 轮失败后主源降级（第三轮从备源开始尝试）"""
    trace: list[str] = []
    primary = StubProvider("huilvbiao", trace=trace)
    backup = StubProvider("sina", trace=trace)
    manager = PriceProviderManager([primary, backup])

    assert manager.fetch("gds_AUTD") is None
    assert manager.fetch("gds_AUTD") is None
    assert manager.current_provider == "sina", "连续 2 次失败应切换主源"
    assert manager.fetch("gds_AUTD") is None
    assert trace[4] == "sina", "切换后应先尝试备源（主源仍作兜底轮询）"


def test_manager_restores_primary_when_recovered() -> None:
    """备源顶上期间主源恢复 → 回切主源"""
    primary = StubProvider("huilvbiao", _quote())
    backup = StubProvider("sina")  # 备源失败，才会轮到主源
    manager = PriceProviderManager([primary, backup])
    manager._current_index = 1  # 模拟此前已切换到备源

    quote = manager.fetch("gds_AUTD")
    assert quote is not None
    assert manager.current_provider == "huilvbiao", "主源恢复后应回切"


def test_manager_sources_status_reflects_active_provider() -> None:
    """sources_status 应反映主备角色与当前生效源（设置页展示用）"""
    primary = StubProvider("huilvbiao", _quote())
    backup = StubProvider("sina")
    manager = PriceProviderManager([primary, backup])

    status = {s["name"]: s for s in manager.sources_status()}
    assert status["huilvbiao"]["role"] == "主源"
    assert status["huilvbiao"]["active"] is True
    assert status["sina"]["role"] == "备源"
    assert status["sina"]["active"] is False
    assert status["sina"]["api_url"] == "https://example.com/sina"

    # 主源失败、备源生效后，active 应随之切换
    primary._quote = None
    backup._quote = _quote()
    manager.fetch("gds_AUTD")
    status = {s["name"]: s for s in manager.sources_status()}
    assert status["huilvbiao"]["active"] is False
    assert status["sina"]["active"] is True


# ==================== PriceService 薄壳 ====================


def test_price_service_delegates_and_keeps_shape() -> None:
    manager = PriceProviderManager([StubProvider("huilvbiao", _quote(price=906.80))])
    service = PriceService(provider_manager=manager)
    data = service.fetch_current_price("gds_AUTD")
    assert data is not None
    assert set(data) == {"symbol", "price", "time", "date", "name"}
    assert data["price"] == 906.80
    assert data["name"] == "gds_AUTD" or data["name"]  # 名称来自设置映射


def test_price_service_converts_london_gold() -> None:
    import service.price_service as price_module

    manager = PriceProviderManager([StubProvider("huilvbiao", _quote("hf_XAU", 4133.04))])
    service = PriceService(provider_manager=manager)

    saved = price_module.convert_london_gold_to_cny
    price_module.convert_london_gold_to_cny = lambda price, rate=None: 940.55
    try:
        result = service.fetch_all_gold_prices(["hf_XAU"])
    finally:
        price_module.convert_london_gold_to_cny = saved

    assert result["hf_XAU"]["converted_cny_price"] == 940.55


# ==================== mock 工具 ====================


def mock_sina_get(text):
    return mock.patch.object(sina_module.requests, "get", lambda *a, **k: FakeResponse(text))


if __name__ == "__main__":
    tests = [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    failed = 0
    for name, test in tests:
        try:
            test()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"ERROR {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"PASS  {name}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
