from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False)
    cron_expression: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_scrape_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    json_schema: Mapped[str | None] = mapped_column(Text, nullable=True)
    options_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    status_text: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    max_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    concurrency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    use_proxy: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    detail_url_pattern: Mapped[str | None] = mapped_column(String(500), nullable=True)
    schema_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_items_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
