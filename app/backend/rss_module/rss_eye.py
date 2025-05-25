import argparse
from datetime import datetime, timezone, timedelta
import time
import logging
import asyncio
from typing import Dict, List
from urllib.parse import urlparse
from contextlib import asynccontextmanager
import aiosqlite
import feedparser
from aiogram import Bot
from pydantic import BaseModel
import json


class Settings(BaseModel):
    rss_urls: List[str]
    keywords: List[str]
    tg_bot_token: str
    tg_bot_approved_users: List[int]

    @classmethod
    def from_json(cls, path: str = "rss_eye_config.json") -> "Settings":
        with open(path, "r", encoding="utf-8") as f:
            return cls(**json.load(f))


def setup_logger(name: str, log_file: str, level=logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.hasHandlers():
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        fh = logging.FileHandler(log_file, encoding="utf-8")
        sh = logging.StreamHandler()
        fh.setFormatter(formatter)
        sh.setFormatter(formatter)
        logger.addHandler(fh)
        logger.addHandler(sh)

    return logger


logger = setup_logger("rss_eye", "rss_module.log")


class RSSEye:
    def __init__(self, config: Settings, db_name: str = 'rss_eye.db'):
        self.config = config
        self.rss_urls = config.rss_urls
        self.keywords = config.keywords
        self.db_name = db_name
        self.db = None
        #self.bot = Bot(token=config.tg_bot_token)
        #self.approved_users = config.tg_bot_approved_users
        self.shutdown_event = asyncio.Event()

    @asynccontextmanager
    async def database_connection(self):
        if not self.db:
            self.db = await aiosqlite.connect(self.db_name)
        try:
            yield self.db
        finally:
            if self.db:
                await self.db.commit()
                await self.db.close()
                self.db = None

    async def setup_database(self):
        query = """
                CREATE TABLE IF NOT EXISTS rss_mentions \
                ( \
                    id               INTEGER PRIMARY KEY AUTOINCREMENT, \
                    mention_datetime TEXT NOT NULL, \
                    rss_url          TEXT NOT NULL, \
                    entry_title      TEXT, \
                    entry_link       TEXT, \
                    entry_summary    TEXT
                ) \
                """
        async with self.database_connection() as db:
            await db.execute(query)
        logger.info("Таблица упоминаний проверена или создана.")

    def contains_keywords(self, entry: Dict) -> bool:
        text = entry.get("title", "") + entry.get("summary", "") + entry.get("link", "")
        if "content" in entry:
            for content in entry["content"]:
                text += content.get("value", "")
        return any(kw.lower() in text.lower() for kw in self.keywords)

    async def process_rss_feed(self, url: str):
        logger.info(f"Проверка RSS-ленты: {url}")
        try:
            feed = feedparser.parse(url)
            if feed.bozo:
                logger.error(f"Ошибка парсинга RSS: {feed.bozo_exception}")
                return

            is_google_alert = any(sub in urlparse(url).netloc for sub in ["alerts.google.com", "google.com"])

            for entry in feed.get("entries", []):
                try:
                    if not is_google_alert and not self.contains_keywords(entry):
                        continue

                    published_parsed = entry.get("published_parsed")
                    if isinstance(published_parsed, time.struct_time):
                        dt_utc = datetime.fromtimestamp(time.mktime(published_parsed), tz=timezone.utc)
                    else:
                        dt_utc = datetime.now(tz=timezone.utc)

                    data = {
                        "mention_datetime": dt_utc,
                        "rss_url": url,
                        "entry_title": entry.get("title", ""),
                        "entry_summary": entry.get("summary", ""),
                        "entry_link": entry.get("link", "")
                    }

                    await self.save_mention_to_db(data)
                    # await self.notify_telegram_bot(data)

                except Exception as e:
                    logger.error(f"Ошибка при обработке записи RSS: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Ошибка при запросе RSS: {e}", exc_info=True)

    async def save_mention_to_db(self, mention: Dict):
        query = """
                INSERT INTO rss_mentions (mention_datetime, rss_url, entry_title, entry_summary, entry_link)
                VALUES (?, ?, ?, ?, ?) \
                """
        async with self.database_connection() as db:
            await db.execute(query, (
                mention["mention_datetime"].isoformat(),
                mention["rss_url"],
                mention["entry_title"],
                mention["entry_summary"],
                mention["entry_link"]
            ))
        logger.info(f"Сохранено в БД: {mention['entry_title']}")

    async def notify_telegram_bot(self, mention: Dict):
        dt_local = mention["mention_datetime"] + timedelta(hours=3)
        text = (
            f"📰 <b>Новое упоминание в RSS</b>\n"
            f"🕒 <b>Время:</b> {dt_local.strftime('%d.%m.%Y %H:%M:%S')} (МСК)\n"
            f"📌 <b>Заголовок:</b> {mention['entry_title']}\n"
            f"💬 <b>Описание:</b> {mention['entry_summary']}\n"
            f"🔗 <a href=\"{mention['entry_link']}\">Перейти к записи</a>"
        )
        for user in self.approved_users:
            try:
                await self.bot.send_message(chat_id=user, text=text, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления пользователю {user}: {e}", exc_info=True)

    async def run(self, interval: int = 300):
        await self.setup_database()
        while not self.shutdown_event.is_set():
            await asyncio.gather(*(self.process_rss_feed(url) for url in self.rss_urls))
            await asyncio.sleep(interval)
        # await self.bot.session.close()


async def main():
    parser = argparse.ArgumentParser(description="RSS Eye Arguments Parser")
    parser.add_argument(
        "--config",
        type=str,
        default="rss_eye_config.json",
        help="Путь к JSON-файлу конфигурации RSS Eye",
    )
    args = parser.parse_args()

    config = Settings.from_json(args.config)
    app = RSSEye(config)
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
