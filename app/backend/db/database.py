# backend/db/database.py

import aiosqlite
import datetime
import logging

# Настройка логирования
logger = logging.getLogger("joint_db")
logger.setLevel(logging.INFO)

# Убедимся, что логгер настроен только один раз
if not logger.hasHandlers():
    handlers = [
        logging.FileHandler("joint_db.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    for handler in handlers:
        handler.setFormatter(formatter)
        logger.addHandler(handler)

logger.debug("Логгер настроен")

DB_PATH = "joint.db"

CREATE_TABLE_QUERY = """
CREATE TABLE IF NOT EXISTS mentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    mention_datetime TEXT NOT NULL,
    mention_link TEXT,
    source_id TEXT,
    source_link TEXT,
    user_id TEXT,
    user_name TEXT,
    user_nick TEXT,
    mention_text TEXT
)
"""

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_TABLE_QUERY)
        await db.commit()
    logger.info("Таблица mentions проверена или создана.")

async def insert_mention(
    platform: str,
    mention_datetime: str,
    mention_link: str,
    source_id: str,
    source_link: str,
    user_id: str,
    user_name: str,
    user_nick: str,
    mention_text: str
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO mentions (
                platform,
                mention_datetime,
                mention_link,
                source_id,
                source_link,
                user_id,
                user_name,
                user_nick,
                mention_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                platform,
                mention_datetime,
                mention_link,
                source_id,
                source_link,
                user_id,
                user_name,
                user_nick,
                mention_text,
            )
        )
        await db.commit()

async def get_mentions():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, platform, mention_datetime, mention_link, source_id, source_link, user_id, user_name, user_nick, mention_text FROM mentions ORDER BY mention_datetime DESC"
        )
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
            })
        return mentions