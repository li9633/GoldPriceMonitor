from typing import Any

import requests

from utils.logger import get_logger

logger = get_logger("HttpUtils")

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
}


def get_headers() -> dict[str, str]:
    return _DEFAULT_HEADERS.copy()


def safe_get(
    url: str, params: dict | None = None, timeout: int = 10
) -> requests.Response | None:
    try:
        response = requests.get(
            url, headers=_DEFAULT_HEADERS, params=params, timeout=timeout
        )
        response.encoding = "utf-8"
        response.raise_for_status()
        return response
    except requests.RequestException as e:
        logger.error(f"HTTP GET 请求失败 [{url}]: {e}")
        return None


def safe_post_json(
    url: str, payload: dict[str, Any], timeout: int = 10
) -> requests.Response | None:
    try:
        response = requests.post(url, json=payload, timeout=timeout)
        return response
    except requests.RequestException as e:
        logger.error(f"HTTP POST 请求失败 [{url}]: {e}")
        return None
