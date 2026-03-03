from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.database import init_db
from core.scheduler import start_scheduler, shutdown_scheduler
from core.worker import start_workers, stop_workers
from models import extract_job, extract_result, job_page, log, task
from routers.dashboard import router as dashboard_router
from routers.extract import router as extract_router
from routers.health import router as health_router
from routers.jobs import router as jobs_router
from routers.logs import router as logs_router
from routers.results import router as results_router
from routers.tasks import router as tasks_router

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(extract_router)
app.include_router(tasks_router)
app.include_router(logs_router)
app.include_router(jobs_router)
app.include_router(results_router)
app.include_router(dashboard_router)


@app.on_event("startup")
async def on_startup():
    await init_db()
    await start_scheduler()
    await start_workers()


@app.on_event("shutdown")
async def on_shutdown():
    shutdown_scheduler()
    await stop_workers()
