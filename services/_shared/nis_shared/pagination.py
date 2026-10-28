"""分页参数与响应封装。

统一 ``page`` / ``page_size``（默认 20、最大 100）+ ``total``，
见 ``docs/api-catalog.md`` 第 1 节与 ``common.yaml#PageMeta``。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from fastapi import Query

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

T = TypeVar("T")


@dataclass(frozen=True)
class PageQuery:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_query(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(
        DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="每页条数，最大 100"
    ),
) -> PageQuery:
    return PageQuery(page=page, page_size=page_size)


def page_payload(items: list[T], query: PageQuery, total: int) -> dict[str, object]:
    return {
        "items": items,
        "page": query.page,
        "page_size": query.page_size,
        "total": total,
    }
