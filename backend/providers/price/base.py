"""黄金价格数据源抽象（infra-refactor-plan §3）。

与汇率（`providers/`）、日历（`providers/calendar/`）同一模式：
调用方只认接口，数据源可替换。

报价结构 `PriceQuote` 只携带**源数据**（价格与交易时间），
品种中文名、人民币折算等展示层逻辑留在 `PriceService`。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

#: 新浪系行情文本的字段位置（huilvbiao 为新浪的代理，布局一致）。
#: gds_AUTD 与 hf_XAU 实测布局相同：price=0, time=6, date=12
FIELD_INDEX_MAP = {"default": {"price": 0, "time": 6, "date": 12}}


@dataclass
class PriceQuote:
    """单个品种的源报价"""

    symbol: str
    price: float
    trade_time: str = ""
    trade_date: str = ""


class PriceProvider(ABC):
    """金价数据源抽象基类"""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def api_url(self) -> str:
        """数据端点（供设置页展示；含 {symbol} 占位符的为按品种请求）"""
        ...

    @abstractmethod
    def fetch(self, symbol: str) -> PriceQuote | None:
        """获取单品种报价；失败返回 None（不抛异常）"""
