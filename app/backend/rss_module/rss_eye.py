import argparse
from datetime import datetime, timezone, timedelta
import time
import logging
import asyncio
from typing import Dict, List, Optional
from urllib.parse import urlparse
import aiohttp
from pydantic import BaseModel, HttpUrl
import json
from cachetools import TTLCache
from tenacity import retry, stop_after_attempt, wait_exponential
import feedparser
import aiosqlite
import re

from app.backend.db.database import Platform, insert_mention, add_source, get_active_sources

class Settings(BaseModel):
    rss_urls: List[HttpUrl]
    keywords: List[str]
    check_interval: int = 300  # секунд
    max_retries: int = 3
    cache_ttl: int = 3600  # секунд (1 час)
    proxy: Optional[str] = None

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
    def __init__(self, config: Settings):
        self.config = config
        self.rss_urls = config.rss_urls
        self.keywords = config.keywords
        self.shutdown_event = asyncio.Event()
        self.cache = TTLCache(maxsize=100, ttl=config.cache_ttl)
        self.session = None

    async def init_session(self):
        if self.session is None:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )

    async def close_session(self):
        if self.session:
            await self.session.close()
            self.session = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        reraise=True
    )
    async def fetch_feed(self, url: str) -> Optional[Dict]:
        """Обновляет RSS-ленту с механизмом повторных попыток"""
        cache_key = f"feed_{url}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        try:
            await self.init_session()
            async with self.session.get(url, proxy=self.config.proxy) as response:
                if response.status == 200:
                    content = await response.text()
                    feed = feedparser.parse(content)
                    if not feed.bozo:
                        self.cache[cache_key] = feed
                        return feed
                    else:
                        logger.error(f"Ошибка парсинга ленты: {feed.bozo_exception}")
                else:
                    logger.error(f"Ошибка HTTP {response.status} для {url}")
        except Exception as e:
            logger.error(f"Ошибка обновления ленты {url}: {str(e)}")
            raise
        return None

    def contains_keywords(self, entry: Dict) -> bool:
        """Проверяет, содержит ли статья любое из ключевых слов как целое слово"""
        # Собираем весь текст в одну строку
        text = " ".join([
            entry.get("title", ""),
            entry.get("summary", ""),
            entry.get("link", ""),
            *[content.get("value", "") for content in entry.get("content", [])]
        ]).lower()
        
        # Для каждого ключевого слова создаем паттерн с границами слов
        for keyword in self.keywords:
            # Экранируем специальные символы в ключевом слове
            escaped_keyword = re.escape(keyword.lower())
            # Создаем паттерн для поиска целого слова
            pattern = r'\b' + escaped_keyword + r'\b'
            if re.search(pattern, text):
                return True
        
        return False

    def is_google_source(self, source_domain: str) -> tuple[bool, str]:
        """Определяет тип Google-источника и возвращает (is_google, source_type)"""
        if "news.google.com" in source_domain:
            return True, "google_news"
        elif "alerts.google.com" in source_domain:
            return True, "google_alerts"
        return False, "other"

    def extract_entry_data(self, entry: Dict, source_url: str) -> Dict:
        """Извлекает и нормализует данные статьи"""
        published_parsed = entry.get("published_parsed")
        if isinstance(published_parsed, time.struct_time):
            dt_utc = datetime.fromtimestamp(time.mktime(published_parsed), tz=timezone.utc)
        else:
            dt_utc = datetime.now(tz=timezone.utc)

        source_domain = urlparse(source_url).netloc
        source_name = entry.get("feed", {}).get("title", source_domain)

        # Определяем тип источника
        is_google, source_type = self.is_google_source(source_domain)

        # Универсальное извлечение текста с учетом типа источника
        title = entry.get("title", "")
        if source_type == "google_news":
            # Google News часто использует description вместо summary
            summary = entry.get("description", "") or entry.get("summary", "")
        else:
            summary = entry.get("summary", "") or entry.get("description", "")

        link = entry.get("link", "")

        # Для Google News добавляем дополнительную информацию
        if source_type == "google_news":
            source_name = "Google News"
            # Добавляем информацию о публикации, если есть
            publisher = entry.get("source", {}).get("title", "")
            if publisher:
                summary = f"Источник: {publisher}\n{summary}"

        return {
            "mention_datetime": dt_utc.isoformat(),
            "mention_link": link,
            "source_id": source_domain,
            "source_link": source_url,
            "user_id": "",
            "user_name": entry.get("author", ""),
            "user_nick": "",
            "mention_text": f"{title}\n{summary}",
            "feed_url": source_url,
            "entry_title": title,
            "entry_summary": summary,
            "source_type": source_type  # Добавляем тип источника
        }

    async def process_rss_feed(self, url: str):
        """Обрабатывает одну RSS-ленту"""
        logger.info(f"Проверяю RSS-ленту: {url}")
        try:
            feed = await self.fetch_feed(url)
            if not feed:
                return

            # Добавляем источник в базу данных
            source_domain = urlparse(url).netloc
            source_name = feed.get("feed", {}).get("title", source_domain)
            await add_source(Platform.RSS, source_domain, source_name, url)

            # Определяем тип источника
            is_google, source_type = self.is_google_source(source_domain)

            for entry in feed.get("entries", []):
                try:
                    link = entry.get("link", "")
                    if not link:
                        continue
                    if await mention_exists(link):
                        continue  # Уже есть в БД, пропускаем

                    # Для Google News и Alerts пропускаем проверку ключевых слов
                    if not is_google and not self.contains_keywords(entry):
                        continue

                    mention_data = self.extract_entry_data(entry, url)
                    await insert_mention(Platform.RSS, mention_data)
                except Exception as e:
                    logger.error(f"Ошибка обработки RSS-статьи: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Ошибка обработки RSS-ленты {url}: {e}", exc_info=True)

    async def run(self):
        """Запускает основный цикл"""
        try:
            while not self.shutdown_event.is_set():
                await asyncio.gather(
                    *(self.process_rss_feed(str(url)) for url in self.rss_urls)
                )
                await asyncio.sleep(self.config.check_interval)
        finally:
            await self.close_session()

async def main():
    parser = argparse.ArgumentParser(description="Парсер аргументов RSS Eye")
    parser.add_argument(
        "--config",
        type=str,
        default="rss_eye_config.json",
        help="Путь к JSON-файлу конфигурации RSS Eye",
    )
    args = parser.parse_args()

    config = Settings.from_json(args.config)
    app = RSSEye(config)
    
    try:
        await app.run()
    except KeyboardInterrupt:
        logger.info("Останавливаю RSS Eye...")
        app.shutdown_event.set()
    except Exception as e:
        logger.error(f"Непредвиденная ошибка: {e}", exc_info=True)
    finally:
        await app.close_session()

async def mention_exists(link: str) -> bool:
    DB_PATH = "app/backend/db/joint.db"
    query = "SELECT 1 FROM rss_mentions WHERE mention_link = ? LIMIT 1"
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(query, (link,))
        result = await cursor.fetchone()
        return result is not None

if __name__ == "__main__":
    asyncio.run(main())
