from fastapi import APIRouter, Query
from typing import Optional, List
from datetime import datetime, timedelta
import logging
from app.backend.db.database import get_mentions, Platform, get_active_sources, get_active_keywords

# Настройка логирования
logger = logging.getLogger("dashboard")
logger.setLevel(logging.INFO)

if not logger.hasHandlers():
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)

router = APIRouter()

@router.get("/dashboard_data")
async def dashboard_data(
    platform: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    source_id: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0)
):
    # Если даты не указаны, берем последние 7 дней
    if not start_date:
        start_date = (datetime.now() - timedelta(days=7)).isoformat()
    if not end_date:
        end_date = datetime.now().isoformat()

    logger.info(f"Получение данных с параметрами: platform={platform}, start_date={start_date}, end_date={end_date}, source_id={source_id}")

    # Получаем упоминания с фильтрацией
    mentions = await get_mentions(
        platform=Platform(platform) if platform else None,
        start_date=start_date,
        end_date=end_date,
        source_id=source_id,
        limit=limit,
        offset=offset
    )

    logger.info(f"Получено упоминаний: {len(mentions)}")

    # Получаем активные источники
    sources = await get_active_sources(
        platform=Platform(platform) if platform else None
    )

    logger.info(f"Получено источников: {len(sources)}")

    # Получаем активные ключевые слова
    keywords = await get_active_keywords()

    logger.info(f"Получено ключевых слов: {len(keywords)}")

    return {
        "mentions": mentions,
        "sources": sources,
        "keywords": keywords,
        "filters": {
            "platform": platform,
            "start_date": start_date,
            "end_date": end_date,
            "source_id": source_id,
            "limit": limit,
            "offset": offset
        }
    }
