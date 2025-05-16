from datetime import datetime, timezone, timedelta
import time
import signal
import json
import html
import logging
import asyncio
from contextlib import asynccontextmanager
from typing import Dict, List
import aiosqlite
import feedparser
from urllib.parse import urlparse
from aiogram import Bot as TgBot

# Настройка логирования
def setup_logger(name: str, log_file: str, level=logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


logger = setup_logger("rss_eye", "rss_module.log")


def load_config() -> dict:
    try:
        with open("rss_eye_config.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки конфигурации: {e}")
        raise


class RSSEye:
    #def __init__(self, rss_urls: List[str], keywords: List[str], tg_bot_token: str, tg_bot_approved_users: List[int], db_name: str = 'rss_eye.db'):
    def __init__(self, rss_urls: List[str], keywords: List[str], db_name: str = 'rss_eye.db'):
        self.rss_urls = rss_urls
        self.keywords = keywords
        self.db_name = db_name
        self.db = None
        #self.tg_bot = TgBot(token=tg_bot_token)
        #self.tg_bot_approved_users = tg_bot_approved_users
        self.last_checked = {url: datetime.min for url in rss_urls}
        self.shutdown_event = asyncio.Event()
        self._tasks = []

        logger.debug("Экземпляр класса RSSEye создан")

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
        CREATE TABLE IF NOT EXISTS rss_mentions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mention_datetime TEXT NOT NULL,
            rss_url TEXT NOT NULL,
            entry_id TEXT,
            entry_title TEXT,
            entry_link TEXT,
            entry_summary TEXT        
        )
        """
        async with self.database_connection() as db:
            await db.execute(query)

        logger.info("Таблица упоминаний проверена или создана.")

    def contains_keywords(self, entry: Dict) -> bool:
        text_to_check = entry.get("title", "") + " "  # Заголовок
        text_to_check += entry.get("summary", "") + " "  # Описание
        if "content" in entry:  # Полный текст
            for content in entry["content"]:
                text_to_check += content.get("value", "") + " "
        text_to_check += entry.get("link", "")  # Ссылка
        return any(keyword.lower() in text_to_check.lower() for keyword in self.keywords)

    async def process_rss_feed(self, url: str):
        logger.info(f"Проверка RSS-ленты: {url}")
        try:
            feed = feedparser.parse(url)
            if feed.bozo:
                logger.error(f"Ошибка парсинга RSS: {feed.bozo_exception}")
                return

            is_google_alert = any(substring in urlparse(url).netloc for substring in ["alerts.google.com", "google.com/alerts"])

            for entry in feed.get("entries", []):
                if not is_google_alert and not self.contains_keywords(entry):
                    continue

                # Преобразование времени публикации в UTC
                published_parsed = entry.get("published_parsed")
                if isinstance(published_parsed, time.struct_time):
                    mention_datetime = datetime.fromtimestamp(
                        time.mktime(published_parsed), tz=timezone.utc
                    )
                else:
                    logger.warning(f"Не удалось определить время публикации для записи: {entry.get('title', 'Без названия')}")
                    mention_datetime = datetime.now(tz=timezone.utc)  # Используем текущее время как fallback

                mention_data = {
                    'mention_datetime': mention_datetime,
                    'feed_url': url,
                    'title': entry.get("title", ""),
                    'summary': entry.get("summary", ""),
                    'link': entry.get("link", "")
                }
                await self.save_mention_to_db(mention_data)
                #await self.notify_telegram_bot(mention_data)
        except Exception:
            logger.error(f"Ошибка при обработке записи: {entry.get('title', 'Без названия')}", exc_info=True)

    async def save_mention_to_db(self, mention_data: Dict):
        try:
            query = """
            INSERT INTO rss_mentions (mention_datetime, rss_url, entry_title, entry_summary, entry_link)
            VALUES (?, ?, ?, ?, ?)        
            """
            async with self.database_connection() as db:
                await db.execute(query, (
                    mention_data["mention_datetime"].isoformat(),
                    mention_data["feed_url"],
                    mention_data["title"],
                    mention_data["summary"],
                    mention_data["link"]
                ))
            logger.info(f"Упоминание в записи {mention_data['title']} сохранено в БД")
        except Exception as e:
            logger.error(f"Ошибка при записи упоминания в БД: {e}", exc_info=True)

    async def notify_telegram_bot(self, mention_data: Dict):
        local_time = mention_data["mention_datetime"] + timedelta(hours=3)

        notification_text = (
            f"📰 <b>Новое упоминание в RSS-ленте</b>\n"
            f"⌚ <b>Время:</b> {local_time.strftime('%d.%m.%Y %H:%M:%S')} (МСК)\n"
            f"✏ <b>Название:</b> {mention_data['title']}\n"
            f"📄 <b>Текст:</b> {mention_data['summary']}\n"
            f"🔗 <b>Ссылка:</b> {mention_data['link']}"
        )

        for user in self.tg_bot_approved_users:
            try:
                await self.tg_bot.send_message(chat_id=user, text=notification_text, parse_mode="HTML")
                logger.info(f"Уведомление отправлено пользователю {user}")
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления пользователю {user}: {e}", exc_info=True)

    async def run(self, interval=300):
        logger.info("Запуск RSS Eye...")
        while not self.shutdown_event.is_set():
            tasks = [self.process_rss_feed(url) for url in self.rss_urls]
            await asyncio.gather(*tasks)
            try:
                await asyncio.wait_for(self.shutdown_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue
        await self.graceful_shutdown()

    async def graceful_shutdown(self):
        logger.info("Завершение работы...")
        if self.db:
            await self.db.close()
        #await self.tg_bot.session.close()
        logger.info("Работа завершена")

async def main():
    config = load_config()
    rss_eye = RSSEye(
        rss_urls=config["rss_urls"],
        keywords=config["keywords"],
        #tg_bot_token=config["tg_bot_token"],
        #tg_bot_approved_users=config["tg_bot_approved_users"]
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, rss_eye.shutdown_event.set)

    await rss_eye.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Процесс прерван сигналом SIGINT (keyboard interrupt)")