from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from models.log import Log

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/stats")
async def get_stats(session: AsyncSession = Depends(get_session)):
    now = datetime.utcnow()
    today_start = datetime.combine(now.date(), datetime.min.time())

    today_tokens = await session.scalar(
        select(func.coalesce(func.sum(Log.token_usage), 0)).where(Log.execution_time >= today_start)
    )
    total_items = await session.scalar(select(func.coalesce(func.sum(Log.items_count), 0)))
    error_count = await session.scalar(select(func.count()).where(Log.status == "failed"))

    return {
        "today_tokens": int(today_tokens or 0),
        "total_items": int(total_items or 0),
        "error_count": int(error_count or 0),
    }


@router.get("/chart")
async def get_chart(
    period: str = Query(default="7d", pattern="^(7d|30d)$"),
    session: AsyncSession = Depends(get_session),
):
    days = 7 if period == "7d" else 30
    now = datetime.utcnow()
    start_dt = datetime.combine((now - timedelta(days=days - 1)).date(), datetime.min.time())

    result = await session.execute(
        select(
            func.date(Log.execution_time).label("day"),
            func.sum(case((Log.status == "success", 1), else_=0)).label("success_count"),
            func.count(Log.id).label("total_count"),
        )
        .where(Log.execution_time >= start_dt)
        .group_by(func.date(Log.execution_time))
        .order_by(func.date(Log.execution_time))
    )

    points = []
    for day, success_count, total_count in result.all():
        total = int(total_count or 0)
        success = int(success_count or 0)
        success_rate = round((success / total) * 100, 2) if total else 0.0
        points.append(
            {
                "date": str(day),
                "success_count": success,
                "total_count": total,
                "success_rate": success_rate,
            }
        )
    return {"period": period, "points": points}


@router.get("/alerts")
async def get_alerts(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(
            Log.error_message,
            func.count().label("count"),
        )
        .where(Log.status == "failed", Log.error_message.is_not(None))
        .group_by(Log.error_message)
        .order_by(func.count().desc())
        .limit(10)
    )
    alerts = [{"error_message": msg, "count": int(count)} for msg, count in result.all()]
    return {"alerts": alerts}
