import signal
import getpass
import html
from datetime import timedelta
import logging
import asyncio
import aiosqlite
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from aiogram import Bot
from config_encryption import check_and_encrypt, read_encrypted_config

# Настройка логирования
logger = logging.getLogger("telegram_eye")
logger.setLevel(logging.INFO)

# Убедимся, что логгер настроен только один раз
if not logger.hasHandlers():
    handlers = [
        logging.FileHandler("telegram_module.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    for handler in handlers:
        handler.setFormatter(formatter)
        logger.addHandler(handler)

logger.debug("Логгер настроен")

class TelegramEye:
    def __init__(self, api_id, api_hash, phone, keywords, bot_token, approved_users, db_name='telegram_eye_msgs.db', session_file='MMIS-TGE.session'):
        # Инициализация параметров для подключения к Telegram-клиенту, боту и базе данных
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.session_file = session_file
        self.client = TelegramClient(self.session_file, api_id, api_hash, device_model="Intel Z690", system_version="Windows 10")
        self.db_name = db_name
        self.db = None
        self.keywords = keywords
        self.bot = Bot(token=bot_token)
        self.approved_users = approved_users
        self.shutdown_event = asyncio.Event()
        self._is_running = True

        logger.debug("Создан экземпляр класса TelegramEye.")

    def is_running(self) -> bool:
        return self._is_running

    async def connect_and_authorize(self):
        try:
            await self.client.connect()
            if not await self.client.is_user_authorized():
                logger.info("Требуется авторизация. Отправляем код...")
                await self.client.send_code_request(self.phone, force_sms=False)
                login_code = input("Введите код авторизации\n> ")

                try:
                    await self.client.sign_in(self.phone, code=login_code)
                except SessionPasswordNeededError:
                    password = input("Введите пароль 2FA\n> ")
                    await self.client.sign_in(password=password)

                logger.info("Успешная авторизация!")
            else:
                logger.info("Сессия найдена, авторизация не требуется.")
        except Exception as e:
            logger.error(f"Ошибка при подключении: {e}", exc_info=True)

    # Создаёт таблицу сообщений в базе данных, если её ещё нет
    async def setup_database(self):
        try:
            self.db = await aiosqlite.connect(self.db_name)
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_datetime TEXT NOT NULL,
                    message_link TEXT,
                    chat_id TEXT,
                    chat_link TEXT,
                    user_id INTEGER NOT NULL,
                    user_name TEXT,
                    user_nick TEXT,
                    message_text TEXT
                )
            """)
            await self.db.commit()
            logger.info("Таблица сообщений проверена или создана.")
        except Exception as e:
            logger.error(f"Ошибка при настройке базы данных: {e}", exc_info=True)

    # Обрабатывает входящее сообщение и сохраняет его, если оно содержит ключевые слова
    async def process_message(self, event):
        try:
            msg = event.message # Сущность сообщения
            message_datetime = msg.date  # Дата сообщения
            message_text = event.raw_text or "Нет текста"  # Текст сообщения

            # Проверяем наличие ключевых слов (поиск по подстроке)
            if not any(keyword.lower() in message_text.lower() for keyword in self.keywords):
                return  # Пропускаем сообщение, если ключевые слова отсутствуют

            # Получаем информацию о чате и ссылку на сообщение
            chat_id = msg.chat_id  # ID чата
            chat_link = f"https://t.me/{msg.chat.username}"
            message_id = msg.id  # ID сообщения
            message_link = f"https://t.me/c/{chat_id}/{message_id}"

            # Убираем префикс -100 из message_link, если это первые 4 символа
            if str(chat_id).startswith("-100"):
                message_link = message_link.replace("-100", "", 1)  # Убираем только первый префикс -100

            # Получаем информацию об отправителе
            user_id = event.sender.id
            user_entity = await self.client.get_entity(user_id)
            user_name = user_entity.username or "Юзернейм отсутствует"  # Получаем username, если он есть
            user_nick = f"{user_entity.first_name or ''} {user_entity.last_name or ''}".strip()  # Имя и фамилия пользователя

            logger.info(f"[{message_datetime}] {user_nick} ({user_id} @{user_name}) в чате {chat_link} ({chat_id}): {message_text}")

            # Сохраняем данные в базу
            await self.save_message_to_db(message_datetime, message_link, chat_id, chat_link, user_id, user_name, user_nick, message_text)

            # Пересылаем сообщение в бот
            await self.send_notification(message_datetime, message_link, chat_link, user_id, user_name, user_nick, message_text)

        except Exception as e:
            logger.error(f"Ошибка при обработке сообщения: {e}", exc_info=True)

    # Сохраняет сообщение в базу данных
    async def save_message_to_db(self, message_datetime, message_link, chat_id, chat_link, user_id, user_name, user_nick, message_text):
        try:
            # Формируем запрос к БД
            sqlite_insert_with_param = """
                INSERT INTO messages (message_datetime, message_link, chat_id, chat_link, user_id, user_name, user_nick, message_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """

            # Заполняем данные для вставки в базу данных
            data_tuple = (message_datetime, chat_id, chat_link, user_id, user_name, user_nick, message_link, message_text)
            await self.db.execute(sqlite_insert_with_param, data_tuple)
            await self.db.commit()
            logger.info(f"Сообщение от {user_nick} (@{user_name}) сохранено в базу данных.")
        except Exception as e:
            logger.error(f"Ошибка при записи сообщения в базу данных: {e}", exc_info=True)

    # Отправляет уведомление в Telegram-бота
    async def send_notification(self, message_datetime, message_link, chat_link, user_id, user_name, user_nick, message_text):
        # Преобразуем время в UTC+3 (МСК+0)
        local_time = message_datetime + timedelta(hours=3)

        # Формируем текст уведомления
        notification_text = (
            f"📅 <b>Дата:</b> {local_time.strftime('%d.%m.%Y %H:%M:%S')} (МСК+0)\n"
            f"⛓️ <b>Ссылка на чат:</b> <a href=\"{chat_link}\">{chat_link}</a>\n"
            f"🔗 <b>Ссылка на сообщение:</b> <a href=\"{message_link}\">{message_link}</a>\n"
            f"👤 <b>ID пользователя:</b> <code>{user_id}</code>\n"
            f"🪪 <b>Username:</b> @{user_name if user_name else 'Нет'}\n"
            f"📛 <b>Имя:</b> {user_nick}\n"
            f"💬 <b>Сообщение:</b> {html.escape(message_text)}"
        )

        # Отправляем уведомления всем пользователям из списка approved_users
        for user in self.approved_users:
            try:
                await self.bot.send_message(chat_id=user, text=notification_text, parse_mode="HTML")
                logger.info(f"Уведомление отправлено пользователю {user}")
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления пользователю {user}: {e}", exc_info=True)

    def setup_signal_handler(self) -> None:
        loop = asyncio.get_running_loop()

        def sig_received_handler(signal_received):
            asyncio.create_task(self.shutdown(signal_received))

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda s=sig: sig_received_handler(s))

    # Подготовка к завершению работы
    async def cleanup(self):
        logger.info("Пробую завершить работу правильно...")
        self._is_running = False

        # Отключение бота
        try:
            if self.bot:
                await self.bot.session.close()
                logger.info("Соединение с ботом закрыто.")
        except Exception as e:
            logger.error(f"Ошибка при отключении от бота: {e}", exc_info=True)

        # Отключение клиента Telegram
        try:
            if self.client:
                await self.client.disconnect()
                logger.info("Соединение с клиентом Telegram закрыто.")
        except Exception as e:
            logger.error(f"Ошибка при отключении клиента Telegram: {e}", exc_info=True)

        # Отключение от БД
        try:
            if self.db:
                await self.db.close()
                logger.info("Соединение с БД закрыто.")
        except Exception as e:
            logger.error(f"Ошибка при отключении от БД: {e}", exc_info=True)

    async def shutdown(self, sig: signal.Signals) -> None:
        logger.info(f"Получен сигнал {sig.name}, завершаю работу...")

        # Отключение клиента Telegram
        if self.client.is_connected():
            logger.info("Отключаю клиента Telegram...")
            await self.client.disconnect()

        # Отмена всех задач
        tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        logger.info(f"Отменяю {len(tasks)} задач...")
        for task in tasks:
            task.cancel()

        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            logger.info("Некоторые задачи были отменены.")

        logger.info(f"Завершение работы...")

        # Завершаем цикл событий
        loop = asyncio.get_running_loop()
        loop.stop()

# Основная асинхронная функция для запуска бота
async def main(password: str):
    telegram_eye = None  # Явная инициализация
    try:
        # password = getpass.getpass("Введите пароль для расшифровки конфигурации TelegramEye\n> ")
        check_and_encrypt('telegram_eye_config.json', 'telegram_eye_config.json.enc', password)
        config = read_encrypted_config('telegram_eye_config.json.enc', password)

        API_ID = config['api_id']
        API_HASH = config['api_hash']
        PHONE = config['phone']
        BOT_TOKEN = config['bot_token']
        APPROVED_USERS = config['approved_users']
        KEYWORDS = config['keywords']

        # Инициализация клиента
        telegram_eye = TelegramEye(API_ID, API_HASH, PHONE, KEYWORDS, BOT_TOKEN, APPROVED_USERS)
        telegram_eye.setup_signal_handler()
        await telegram_eye.setup_database()  # Настройка базы данных
        await telegram_eye.connect_and_authorize()  # Подключение (и авторизация) аккаунта

        # Обработчик для мониторинга новых сообщений
        @telegram_eye.client.on(events.NewMessage(chats=None))  # None = слушать все чаты
        async def new_message_listener(event):
            if telegram_eye.is_running:
                await telegram_eye.process_message(event)

        logger.info("Начинаю обрабатывать сообщения. Для завершения используйте Ctrl+C")
        await telegram_eye.client.run_until_disconnected()

    except asyncio.CancelledError:
        logger.info("Программа остановлена по сигналу завершения.")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
    finally:
        if telegram_eye:
            await telegram_eye.cleanup()
