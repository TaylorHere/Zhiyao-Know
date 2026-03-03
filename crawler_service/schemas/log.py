from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int | None
    task_name: str | None = None
    job_id: str | None
    execution_time: datetime
    status: str
    error_message: str | None
    detail_log: str | None = None
    items_count: int
    token_usage: int


class LogListResponse(BaseModel):
    items: list[LogOut]
    total: int
    page: int
    size: int
