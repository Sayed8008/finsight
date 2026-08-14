"""Response shapes shared between feature areas.

`Page` is generic so that every paginated endpoint answers with the same
envelope. A client that can render one page of transactions can then render a
page of anything, and the desktop table's paging controls are written once.
"""

from __future__ import annotations

from math import ceil
from typing import Generic, TypeVar

from pydantic import BaseModel, computed_field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """One page of results, plus what a pager needs to describe the rest.

    `total` is the number of rows matching the filters, not the number
    returned — without it a pager cannot say "page 3 of 12", and the interface
    can only offer "next" and hope. It costs a second `COUNT(*)` over the same
    WHERE clause (ADR-021).
    """

    items: list[T]
    total: int
    page: int
    page_size: int

    @computed_field
    @property
    def pages(self) -> int:
        """How many pages the filtered set spans; zero when nothing matched.

        Derived rather than stored, so it cannot contradict `total` and
        `page_size` (ADR-015 applied to a response body).
        """
        if self.page_size <= 0:
            return 0
        return ceil(self.total / self.page_size)
