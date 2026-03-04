from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from schemas.extract import ExtractOptions

TaskMode = Literal["scrape", "crawl", "list", "auto"]
TaskStatus = Literal["active", "paused"]


class TaskCreate(BaseModel):
    name: str | None = None
    site_name: str | None = None
    url: HttpUrl | None = None
    target_url: HttpUrl | None = None
    frequency: str
    cron_expression: str | None = None
    mode: TaskMode = "scrape"
    detail_url_pattern: str | None = None
    schema: Any | None = None
    json_schema: str | None = None
    max_depth: int = Field(default=1, ge=1)
    concurrency: int = Field(default=1, ge=1, le=20)
    use_proxy: bool = False
    options: ExtractOptions = Field(default_factory=ExtractOptions)
    status: TaskStatus = "active"


class TaskUpdate(BaseModel):
    name: str | None = None
    site_name: str | None = None
    url: HttpUrl | None = None
    target_url: HttpUrl | None = None
    frequency: str | None = None
    cron_expression: str | None = None
    mode: TaskMode | None = None
    detail_url_pattern: str | None = None
    schema: Any | None = None
    json_schema: str | None = None
    max_depth: int | None = Field(default=None, ge=1)
    concurrency: int | None = Field(default=None, ge=1, le=20)
    use_proxy: bool | None = None
    options: ExtractOptions | None = None
    status: TaskStatus | None = None


class TaskToggleRequest(BaseModel):
    active: bool


class TaskStatusUpdate(BaseModel):
    status: bool


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    url: str
    frequency: str
    cron_expression: str | None
    mode: TaskMode
    status: TaskStatus
    detail_url_pattern: str | None
    max_depth: int
    concurrency: int
    use_proxy: bool
    schema: Any | None
    options: ExtractOptions | None
    last_run_time: datetime | None
    last_items_count: int
    last_scrape_time: datetime | None


class TaskListResponse(BaseModel):
    items: list[TaskOut]
    total: int
    page: int
    size: int


class TaskRunResponse(BaseModel):
    job_id: str
    status: str


class ExtractResultOut(BaseModel):
    id: int
    task_id: int | None
    job_id: str | None
    source_url: str
    title: str | None
    publish_date: datetime | None
    data: Any
    created_at: datetime


class TaskResultListResponse(BaseModel):
    items: list[ExtractResultOut]
    total: int
    page: int
    size: int
