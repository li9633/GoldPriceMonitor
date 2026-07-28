from pydantic import BaseModel


class ApiResponse[T](BaseModel):
    """统一响应包装"""

    code: int = 200
    message: str = "success"
    data: T | None = None

    @classmethod
    def ok(cls, data: T, message: str = "success") -> "ApiResponse[T]":
        return cls(code=200, message=message, data=data)

    @classmethod
    def success(cls, message: str = "success") -> "ApiResponse[None]":
        return ApiResponse[None](code=200, message=message, data=None)

    @classmethod
    def fail(cls, message: str, code: int = 400) -> "ApiResponse[None]":
        return ApiResponse[None](code=code, message=message, data=None)


class PageResponse[T](BaseModel):
    """分页响应包装"""

    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int

    @classmethod
    def of(
        cls, items: list[T], total: int, page: int, page_size: int
    ) -> "PageResponse[T]":
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=(total + page_size - 1) // page_size,
        )
