import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    # Chosen by the client so it can cancel while this request is still waiting.
    id: uuid.UUID
    sql: str = Field(min_length=1, max_length=100_000)


class QueryPage(BaseModel):
    id: uuid.UUID
    status: Literal["running", "succeeded", "failed", "cancelled"]
    error: str | None
    elapsed_ms: int
    columns: list[str]
    types: list[str]
    rows: list[list[Any]]
    page: int
    page_size: int
    has_next: bool
    # True when the query had more rows than row_cap; only the first row_cap are pageable.
    capped: bool
    row_cap: int
