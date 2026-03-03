from core.celery_app import celery_app
from core.worker import run_job_sync


@celery_app.task(name="crawler.process_extract_job")
def process_extract_job(job_id: str):
    run_job_sync(job_id)
