# backend/db/database.py

import aiosqlite
import datetime
import logging
from typing import Dict, List, Optional, Union
from enum import Enum

# Настройка логирования
logger = logging.getLogger("joint_db")
logger.setLevel(logging.INFO)

# Убедимся, что логгер настроен только один раз
if not logger.hasHandlers():
    handlers = [
        logging.FileHandler("app/backend/db/joint_db.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    for handler in handlers:
        handler.setFormatter(formatter)
        logger.addHandler(handler)

logger.debug("Логгер настроен")

DB_PATH = "app/backend/db/joint.db"

class Platform(Enum):
    RSS = "rss"
    VK = "vk"
    TELEGRAM = "telegram"

# Базовые поля для всех таблиц упоминаний
BASE_MENTION_FIELDS = """
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mention_datetime TEXT NOT NULL,
    mention_link TEXT,
    source_id TEXT,
    source_link TEXT,
    user_id TEXT,
    user_name TEXT,
    user_nick TEXT,
    mention_text TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
"""

# Создание таблиц для каждого сервиса
CREATE_TABLES_QUERIES = [
    f"""
    CREATE TABLE IF NOT EXISTS rss_mentions (
        {BASE_MENTION_FIELDS},
        feed_url TEXT,
        entry_title TEXT,
        entry_summary TEXT
)
    """,
    f"""
    CREATE TABLE IF NOT EXISTS vk_mentions (
        {BASE_MENTION_FIELDS},
        post_id TEXT,
        group_id TEXT,
        likes_count INTEGER DEFAULT 0,
        reposts_count INTEGER DEFAULT 0,
        comments_count INTEGER DEFAULT 0
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS telegram_mentions (
        {BASE_MENTION_FIELDS},
        chat_id TEXT,
        message_id TEXT,
        reply_to_message_id TEXT,
        forward_from_chat_id TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT NOT NULL,
        source_id TEXT NOT NULL,
        source_name TEXT,
        source_link TEXT,
        is_active BOOLEAN DEFAULT 1,
        last_check TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(platform, source_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS keywords (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword TEXT NOT NULL UNIQUE,
        is_active BOOLEAN DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """
]

async def init_db():
    """Инициализирует базу данных и создаёт все необходимые таблицы"""
    async with aiosqlite.connect(DB_PATH) as db:
        for query in CREATE_TABLES_QUERIES:
            await db.execute(query)
        await db.commit()
    logger.info("База данных инициализирована")

async def insert_mention(platform: Platform, mention_data: Dict):
    """Вставляет упоминания в соответствующую платформе таблицу"""
    table_name = f"{platform.value}_mentions"
    
    # Формируем список полей и значений для вставки
    fields = []
    values = []
    placeholders = []
    
    for field, value in mention_data.items():
        fields.append(field)
        values.append(value)
        placeholders.append("?")
    
    query = f"""
    INSERT INTO {table_name} ({', '.join(fields)})
    VALUES ({', '.join(placeholders)})
    """
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(query, values)
            await db.commit()
            logger.info(f"Упоминание сохранено в таблицу {table_name}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении упоминания в {table_name}: {e}")
        raise

async def get_mentions(
    platform: Optional[Platform] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    source_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> List[Dict]:
    """Полуает упоминания с возможностью фильтрации"""
    # Формируем UNION запрос для всех таблиц упоминаний
    union_queries = []
    params = []
    
    # Если указана платформа, берем только её таблицу
    platforms = [platform] if platform else list(Platform)
    
    for p in platforms:
        conditions = []
        
        if start_date:
            conditions.append("mention_datetime >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("mention_datetime <= ?")
            params.append(end_date)
        if source_id:
            conditions.append("source_id = ?")
            params.append(source_id)
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        union_queries.append(f"""
            SELECT 
                id,
                '{p.value}' as platform,
                mention_datetime,
                mention_link,
                source_id,
                source_link,
                user_id,
                user_name,
                user_nick,
                mention_text,
                created_at
            FROM {p.value}_mentions
            WHERE {where_clause}
        """)
    
    query = f"""
    SELECT * FROM (
        {" UNION ALL ".join(union_queries)}
    )
    ORDER BY mention_datetime DESC
    LIMIT ? OFFSET ?
    """
    
    params.extend([limit, offset])
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            
            mentions = []
            for row in rows:
                mentions.append({
                    "id": row[0],
                    "platform": row[1],
                    "mention_datetime": row[2],
                    "mention_link": row[3],
                    "source_id": row[4],
                    "source_link": row[5],
                    "user_id": row[6],
                    "user_name": row[7],
                    "user_nick": row[8],
                    "mention_text": row[9],
                    "created_at": row[10]
                })
            return mentions
    except Exception as e:
        logger.error(f"Ошибка при получении упоминаний: {e}")
        raise

async def add_source(platform: Platform, source_id: str, source_name: str, source_link: str):
    """Добавляет новый источник"""
    query = """
    INSERT OR REPLACE INTO sources (platform, source_id, source_name, source_link)
    VALUES (?, ?, ?, ?)
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(query, (platform.value, source_id, source_name, source_link))
            await db.commit()
        logger.info(f"Источник {source_name} добавлен/обновлен")
    except Exception as e:
        logger.error(f"Ошибка при добавлении источника: {e}")
        raise

async def add_keyword(keyword: str):
    """Добавляет новое ключевое слово"""
    query = """
    INSERT OR IGNORE INTO keywords (keyword)
    VALUES (?)
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(query, (keyword,))
            await db.commit()
        logger.info(f"Ключевое слово {keyword} добавлено")
    except Exception as e:
        logger.error(f"Ошибка при добавлении ключевого слова: {e}")
        raise

async def get_active_sources(platform: Optional[Platform] = None) -> List[Dict]:
    """Получает список активных источников"""
    query = "SELECT * FROM sources WHERE is_active = 1"
    params = []
    
    if platform:
        query += " AND platform = ?"
        params.append(platform.value)
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            
            sources = []
            for row in rows:
                sources.append({
                    "id": row[0],
                    "platform": row[1],
                    "source_id": row[2],
                    "source_name": row[3],
                    "source_link": row[4],
                    "is_active": bool(row[5]),
                    "last_check": row[6],
                    "created_at": row[7]
                })
            return sources
    except Exception as e:
        logger.error(f"Ошибка при получении списка источников: {e}")
        raise

async def get_active_keywords() -> List[str]:
    """Получает список активных ключевых слов"""
    query = "SELECT keyword FROM keywords WHERE is_active = 1"
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(query)
            rows = await cursor.fetchall()
            return [row[0] for row in rows]
    except Exception as e:
        logger.error(f"Ошибка при получении списка ключевых слов: {e}")
        raise