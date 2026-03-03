from datetime import datetime
from typing import Literal

from pydantic import BaseModel

JobStatus = Literal["pending", "running", "success", "failed"]
TriggerSource = Literal["manual", "schedule", "adhoc", "unknown"]


class JobOut(BaseModel):
    job_id: str
    task_id: int | None
    task_name: str | None
    status: JobStatus
    trigger_source: TriggerSource
    created_at: datetime
    updated_at: datetime
    error_message: str | None
    list_page_count: int = 0
    discovered_links: int = 0
    effective_links: int = 0
    total_pages: int = 0
    pending_pages: int = 0
    running_pages: int = 0
    success_pages: int = 0
    failed_pages: int = 0
    skipped_pages: int = 0


class JobListResponse(BaseModel):
    items: list[JobOut]
    total: int
    page: int
    size: int


class JobPageOut(BaseModel):
    id: int
    job_id: str
    task_id: int | None
    page_url: str
    status: str
    message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    token_usage: int
    content_markdown: str | None = None
    title: str | None = None
    publish_date: datetime | None = None


class JobPageListResponse(BaseModel):
    items: list[JobPageOut]
    total: int
    page: int
    size: int
