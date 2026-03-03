from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


class ExtractOptions(BaseModel):
    html_to_markdown: bool = True
    remove_scripts_styles: bool = True
    include_images: bool = True
    cache_mode: Literal["enabled", "disabled", "read_only", "write_only", "bypass"] = "bypass"
    wait_until: Literal["domcontentloaded", "load", "networkidle", "commit"] = "domcontentloaded"
    page_timeout: int = Field(default=60000, ge=1000, le=300000)
    wait_for: str | None = None
    only_text: bool = False
    remove_forms: bool = False
    exclude_external_links: bool = False
    simulate_user: bool = False
    magic: bool = False
    user_agent: str | None = None


class ExtractRequest(BaseModel):
    url: HttpUrl
    json_schema: str
    options: ExtractOptions = Field(default_factory=ExtractOptions)


class UsageInfo(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = "deepseek-v3"


ExtractJobStatus = Literal["pending", "running", "success", "failed"]


class ExtractJobCreateResponse(BaseModel):
    job_id: str
    status: ExtractJobStatus
    created_at: datetime


class ExtractJobStatusResponse(BaseModel):
    job_id: str
    status: ExtractJobStatus
    created_at: datetime
    updated_at: datetime
    result: Any | None = None
    usage: UsageInfo | None = None
    error_message: str | None = None
