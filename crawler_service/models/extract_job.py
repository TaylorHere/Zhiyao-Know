from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class ExtractJob(Base):
    __tablename__ = "extract_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    task_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tasks.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    usage_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    list_page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discovered_links: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    effective_links: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
