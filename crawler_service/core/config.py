import os

from pydantic import BaseModel


class Settings(BaseModel):
    database_url: str = os.getenv("CRAWLER_DATABASE_URL", "sqlite+aiosqlite:///./crawler.db")
    api_key: str | None = os.getenv("SILICONFLOW_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
    base_url: str = (
        os.getenv("SILICONFLOW_BASE_URL")
        or os.getenv("CRAWLER_LLM_BASE_URL")
        or "https://api.siliconflow.cn/v1"
    )
    llm_model: str = os.getenv("SILICONFLOW_MODEL") or os.getenv("CRAWLER_LLM_MODEL") or "deepseek-v3"
    llm_provider: str = os.getenv("CRAWLER_LLM_PROVIDER") or f"openai/{os.getenv('SILICONFLOW_MODEL') or os.getenv('CRAWLER_LLM_MODEL') or 'deepseek-v3'}"
    worker_concurrency: int = int(os.getenv("CRAWLER_WORKER_CONCURRENCY", "2"))
    use_celery: bool = os.getenv("CRAWLER_USE_CELERY", "true").lower() == "true"
    redis_url: str = os.getenv("CRAWLER_REDIS_URL", "redis://app-redis:6379/0")


settings = Settings()
