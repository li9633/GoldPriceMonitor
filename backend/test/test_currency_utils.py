"""utils.currency_utils 汇率换算测试。"""
from utils.currency_utils import convert_london_gold_to_cny


def test_convert_london_gold_to_cny(monkeypatch):
    # 固定盎司→克换算系数，避免依赖数据库配置
    monkeypatch.setattr("utils.currency_utils._get_ounce_to_gram", lambda: 31.1035)
    # 311.035 / 31.1035 == 10，10 * 7.0 == 70.0，精确断言
    assert convert_london_gold_to_cny(311.035, 7.0) == 70.0


def test_convert_zero_price(monkeypatch):
    monkeypatch.setattr("utils.currency_utils._get_ounce_to_gram", lambda: 31.1035)
    assert convert_london_gold_to_cny(0.0, 7.2) == 0.0


def test_convert_rounds_to_two_decimals(monkeypatch):
    monkeypatch.setattr("utils.currency_utils._get_ounce_to_gram", lambda: 31.1035)
    result = convert_london_gold_to_cny(2300.0, 7.2)
    # 结果应保留两位小数
    assert result == round(2300.0 * 7.2 / 31.1035, 2)
