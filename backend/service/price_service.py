"""价格查询服务 —— 数据源已下沉到 `providers/price/`，本类只做展示层组装。

- 报价获取：委托给 `PriceProviderManager`（huilvbiao 主源，新浪备源）；
- 品种中文名：来自系统设置的 symbol_name_map；
- 伦敦金人民币折算：依赖汇率链，仍在本层做（它是「展示口径」而非源数据）。
"""

from providers.price import PriceProviderManager, get_price_manager
from service.system_settings_service import SystemSettingsService
from utils.currency_utils import convert_london_gold_to_cny
from utils.logger import get_logger

logger = get_logger("PriceService")


class PriceService:
    def __init__(self, provider_manager: PriceProviderManager | None = None):
        self.provider_manager = provider_manager or get_price_manager()
        self._symbol_name_map: dict[str, str] | None = None

    @property
    def symbol_name_map(self) -> dict[str, str]:
        if self._symbol_name_map is None:
            self._symbol_name_map = SystemSettingsService().get_symbol_name_map()
        return self._symbol_name_map

    def refresh_symbol_name_map(self) -> None:
        self._symbol_name_map = None

    def fetch_current_price(self, symbol: str) -> dict | None:
        quote = self.provider_manager.fetch(symbol)
        if quote is None:
            return None
        return {
            "symbol": quote.symbol,
            "price": quote.price,
            "time": quote.trade_time,
            "date": quote.trade_date,
            "name": self.symbol_name_map.get(symbol, symbol),
        }

    def fetch_all_gold_prices(self, symbols: list[str]) -> dict[str, dict | None]:
        results = {}
        for symbol in symbols:
            data = self.fetch_current_price(symbol)
            if data and "hf_XAU" == symbol:
                try:
                    data["converted_cny_price"] = convert_london_gold_to_cny(
                        data["price"], None
                    )
                except RuntimeError as e:
                    logger.warning(f"伦敦金人民币折算失败：{e}")
            results[symbol] = data
            if data:
                logger.info(f"成功获取 {data['name']} ({symbol}): {data['price']}")
            else:
                logger.warning(f"未能获取 {symbol} 的价格数据")
        return results
