from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from core.config import settings

engine = create_async_engine(settings.database_url, future=True)
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
Base = declarative_base()


async def _sqlite_columns(conn, table_name: str) -> set[str]:
    result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
    return {row[1] for row in result.fetchall()}


async def _ensure_sqlite_column(conn, table_name: str, column_name: str, ddl: str):
    columns = await _sqlite_columns(conn, table_name)
    if column_name not in columns:
        await conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {ddl}"))


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.url.get_backend_name() == "sqlite":
            result = await conn.execute(text("PRAGMA table_info(logs)"))
            log_rows = result.fetchall()
            log_columns = {row[1]: row[3] for row in log_rows}
            migration_needed = False
            if "job_id" not in log_columns:
                migration_needed = True
            if log_columns.get("task_id") == 1:
                migration_needed = True
            if migration_needed and log_rows:
                await conn.execute(text("ALTER TABLE logs RENAME TO logs_old"))
                await conn.run_sync(Base.metadata.create_all)
                await conn.execute(
                    text(
                        "INSERT INTO logs (id, task_id, execution_time, status, error_message, items_count) "
                        "SELECT id, task_id, execution_time, status, error_message, items_count FROM logs_old"
                    )
                )
                await conn.execute(text("DROP TABLE logs_old"))

            await _ensure_sqlite_column(conn, "tasks", "json_schema", "json_schema TEXT")
            await _ensure_sqlite_column(conn, "tasks", "options_json", "options_json TEXT")
            await _ensure_sqlite_column(conn, "tasks", "name", "name VARCHAR(255)")
            await _ensure_sqlite_column(conn, "tasks", "url", "url VARCHAR(2048)")
            await _ensure_sqlite_column(conn, "tasks", "status_text", "status_text VARCHAR(20)")
            await _ensure_sqlite_column(conn, "tasks", "mode", "mode VARCHAR(20)")
            await _ensure_sqlite_column(conn, "tasks", "max_depth", "max_depth INTEGER")
            await _ensure_sqlite_column(conn, "tasks", "concurrency", "concurrency INTEGER")
            await _ensure_sqlite_column(conn, "tasks", "use_proxy", "use_proxy BOOLEAN")
            await _ensure_sqlite_column(
                conn, "tasks", "detail_url_pattern", "detail_url_pattern VARCHAR(500)"
            )
            await _ensure_sqlite_column(conn, "tasks", "schema_json", "schema_json TEXT")
            await _ensure_sqlite_column(conn, "tasks", "last_run_time", "last_run_time DATETIME")
            await _ensure_sqlite_column(conn, "tasks", "last_items_count", "last_items_count INTEGER")

            await _ensure_sqlite_column(conn, "extract_jobs", "task_id", "task_id INTEGER")
            await _ensure_sqlite_column(conn, "extract_jobs", "list_page_count", "list_page_count INTEGER DEFAULT 0")
            await _ensure_sqlite_column(conn, "extract_jobs", "discovered_links", "discovered_links INTEGER DEFAULT 0")
            await _ensure_sqlite_column(conn, "extract_jobs", "effective_links", "effective_links INTEGER DEFAULT 0")
            await _ensure_sqlite_column(conn, "logs", "job_id", "job_id VARCHAR(32)")
            await _ensure_sqlite_column(conn, "logs", "token_usage", "token_usage INTEGER DEFAULT 0")
            await _ensure_sqlite_column(conn, "logs", "detail_log", "detail_log TEXT")


async def get_session():
    async with SessionLocal() as session:
        yield session
