from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ResultOut(BaseModel):
    id: int
    task_id: int | None
    task_name: str | None
    job_id: str | None
    source_url: str
    title: str | None
    publish_date: datetime | None
    data: Any
    created_at: datetime


class ResultListResponse(BaseModel):
    items: list[ResultOut]
    total: int
    page: int
    size: int
