import asyncio
import datetime
import json
import logging
import signal
import html
from typing import Dict, List
from contextlib import asynccontextmanager
import aiosqlite
import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
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


logger = setup_logger("vk_eye", "vk_module.log")


def load_config() -> dict:
    with open("vk_eye_config.json", "r", encoding="utf-8") as f:
        return json.load(f)


class VKEye:
    def __init__(self, login: str, password: str, keywords: List[str], tg_bot_token: str,
                 tg_bot_approved_users: List[int], db_name: str = 'vk_eye.db'):
        self.login = login
        self.password = password
        self.keywords = keywords
        self.tg_bot = TgBot(token=tg_bot_token)
        self.tg_bot_approved_users = tg_bot_approved_users
        self.db_name = db_name
        self.db = None

        self.vk_session = None
        self.vk = None
        self.longpoll = None
        self.last_timestamp = int(datetime.datetime.now().timestamp())

        self.shutdown_event = asyncio.Event()
        self._tasks = []

        self.loop = asyncio.get_event_loop()
        self.loop.add_signal_handler(signal.SIGTERM, self.shutdown_event.set)
        self.loop.add_signal_handler(signal.SIGINT, self.shutdown_event.set)

        logger.debug("Экземпляр класса VKEye создан")

    @asynccontextmanager
    async def database_connection(self):
        if not self.db:
            self.db = await aiosqlite.connect(self.db_name)
            await self.setup_database()
        try:
            yield self.db
        finally:
            if self.db:
                await self.db.commit()
                await self.db.close()
                self.db = None

    async def setup_database(self):
        query = """
        CREATE TABLE IF NOT EXISTS vk_mentions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mention_datetime TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT,
            source_name TEXT,
            mention_link TEXT,
            user_id INTEGER NOT NULL,
            user_name TEXT,
            user_nick TEXT,
            mention_text TEXT
        )
        """
        async with self.database_connection() as db:
            await db.execute(query)
        logger.info("Таблица упоминаний проверена или создана.")

    async def connect_to_vk(self):
        try:
            self.vk_session = vk_api.VkApi(self.login, self.password)
            self.vk_session.auth()
            self.vk = self.vk_session.get_api()
            self.longpoll = VkLongPoll(self.vk_session)
            logger.info("Успешное подключение к VK API")
        except Exception as e:
            logger.error(f"Ошибка подключения к VK API: {e}")
            raise

    def contains_keywords(self, text: str) -> bool:
        return any(keyword.lower() in text.lower() for keyword in self.keywords)

    async def process_newsfeed(self):
        try:
            news = self.vk.newsfeed.get(filters='post', start_time=self.last_timestamp, count=100)
            self.last_timestamp = int(datetime.datetime.now().timestamp())

            for item in news['items']:
                post_text = item.get('text', '')
                if not self.contains_keywords(post_text):
                    continue

                mention_data = {
                    'mention_datetime': datetime.datetime.fromtimestamp(item['date']).isoformat(),
                    'source_type': 'post',
                    'source_id': item.get('source_id'),
                    'mention_text': post_text
                }
                await self.save_mention_to_db(mention_data)
                await self.notify_telegram_bot(mention_data)
        except Exception as e:
            logger.error(f"Ошибка обработки новостной ленты: {e}")

    async def save_mention_to_db(self, mention_data: Dict):
        try:
            query = """
            INSERT INTO vk_mentions (mention_datetime, source_type, source_id, mention_text)
            VALUES (?, ?, ?, ?)
            """
            async with self.database_connection() as db:
                await db.execute(query, (
                    mention_data['mention_datetime'],
                    mention_data['source_type'],
                    mention_data['source_id'],
                    mention_data['mention_text']
                ))
            logger.info("Упоминание сохранено в БД")
        except Exception as e:
            logger.error(f"Ошибка при записи упоминания в БД: {e}", exc_info=True)

    async def notify_telegram_bot(self, mention_data: Dict):
        mention_datetime = datetime.datetime.fromisoformat(mention_data['mention_datetime'])
        local_time = mention_datetime - datetime.timedelta(hours=3)

        notification_text = (
            f"🚾 <b>Новое упоминание в VK</b>\n"
            f"⌚ <b>Время:</b> {local_time.strftime('%d.%m.%Y %H:%M:%S')} (МСК)\n"
            f"🛈 <b>Источник:</b> {mention_data['source_name']}\n"
            f"⛓ <b>Ссылка:</b> <a href=\"{mention_data['mention_link']}\">{mention_data['mention_link']}</a>\n"
            f"👤 <b>Пользователь:</b> @{mention_data['user_nick']} ({mention_data['user_name']})\n"
            f"💬 <b>Текст:</b> {html.escape(mention_data['mention_text'])}"
        )

        for user in self.tg_bot_approved_users:
            try:
                await self.tg_bot.send_message(chat_id=user, text=notification_text, parse_mode="HTML")
                logger.info(f"Уведомление отправлено пользователю {user}.")
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления пользователю {user}: {e}")

    async def run(self):
        await self.connect_to_vk()
        self._tasks.append(asyncio.create_task(self.process_newsfeed_loop()))
        await self.shutdown_event.wait()
        await self.graceful_shutdown()

    async def process_newsfeed_loop(self):
        while not self.shutdown_event.is_set():
            await self.process_newsfeed()
            await asyncio.sleep(60)

    async def graceful_shutdown(self):
        logger.info("Завершение работы...")
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.db:
            await self.db.close()
        await self.tg_bot.session.close()
        logger.info("Работа завершена")


async def main():
    config = load_config()
    vk_eye = VKEye(
        login=config["vk_login"],
        password=config["vk_password"],
        keywords=config["keywords"],
        tg_bot_token=config["tg_bot_token"],
        tg_bot_approved_users=config["tg_bot_approved_users"]
    )
    await vk_eye.run()

if __name__ == "__main__":
    asyncio.run(main())