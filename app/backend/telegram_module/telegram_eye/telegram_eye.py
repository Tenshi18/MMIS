import signal
import json
import html
from datetime import timedelta
import logging
import asyncio
import aiosqlite
from telethon import TelegramClient, events
from telethon.tl.types import PeerUser
from telethon.errors import SessionPasswordNeededError
from aiogram import Bot

from backend.db.database import insert_mention

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

def load_config():
    with open('telegram_eye_config.json', 'r') as f:
        return json.load(f)

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

    # Обрабатывает входящее сообщение и сохраняет его, если оно содержит ключевые слова
    async def process_message(self, event):
        try:
            msg = event.message # Сущность сообщения
            message_datetime = msg.date  # Дата сообщения
            message_text = event.raw_text or "Нет текста"  # Текст сообщения

            # Проверяем наличие ключевых слов (поиск по подстроке)
            if not any(keyword.lower() in message_text.lower() for keyword in self.keywords):
                return  # Пропускаем сообщение, если ключевые слова отсутствуют

            # Получаем идентификатор чата
            chat_id = msg.chat_id

            # Формирование ссылки на чат:
            # Если у чата есть username, используем его
            if msg.chat.username:
                chat_link = f"https://t.me/{msg.chat.username}"
            else:
                # Если username отсутствует, предполагаем, что это супергруппа.
                # chat_id для супергруппы имеет вид -100XXXXXXXXX, удаляем префикс "-100"
                chat_id_str = str(chat_id)
                if chat_id_str.startswith("-100"):
                    chat_id_str = chat_id_str.replace("-100", "", 1)
                chat_link = f"https://t.me/c/{chat_id_str}"

            # Формируем ссылку на сообщение.
            message_id = msg.id
            message_link = f"https://t.me/c/{chat_id}/{message_id}"
            if str(chat_id).startswith("-100"):
                message_link = message_link.replace("-100", "", 1) # Если это супергруппа, аналогично удаляем префикс -100

            # Получаем информацию об отправителе
            user_id = event.sender.id
            try:
                user_entity = await self.client.get_entity(msg.sender_id)
            except ValueError:
                user_entity = await self.client.get_entity(PeerUser(msg.sender_id))

            user_id = user_entity.id

            user_name = user_entity.username or "Юзернейм отсутствует"  # Получаем username, если он есть
            user_nick = f"{user_entity.first_name or ''} {user_entity.last_name or ''}".strip()  # Имя и фамилия пользователя

            # Логгируем упоминание
            logger.info(f"[{message_datetime}] {user_nick} ({user_id} @{user_name}) в чате {chat_link} ({chat_id}): {message_text}")

            # Сохраняем в единую таблицу mentions (platform='telegram')
            await insert_mention(
                platform="telegram",
                mention_datetime=message_datetime.isoformat(),
                mention_link=message_link,
                source_id=str(chat_id),
                source_link=chat_link,
                user_id=str(user_id),
                user_name=user_name,
                user_nick=user_nick,
                mention_text=message_text
            )
            logger.info("Упоминание в Telegram сохранено в общую БД.")

            # Пересылаем сообщение в бот
            await self.notify_bot(message_datetime, message_link, chat_link, user_id, user_name, user_nick, message_text)

        except Exception as e:
            logger.error(f"Ошибка при обработке сообщения: {e}", exc_info=True)

    # Сохраняет сообщение в базу данных
    async def save_message_to_db(self, message_datetime, message_link, chat_id, chat_link, user_id, user_name, user_nick, message_text):
        try:
            # Формируем запрос к БД
            sqlite_insert_with_param = """
                INSERT INTO tg_mentions (message_datetime, message_link, chat_id, chat_link, user_id, user_name, user_nick, message_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """

            # Заполняем данные для вставки в БД
            data_tuple = (message_datetime, chat_id, chat_link, user_id, user_name, user_nick, message_link, message_text)
            await self.db.execute(sqlite_insert_with_param, data_tuple)
            await self.db.commit()
            logger.info(f"Сообщение от {user_nick} (@{user_name}) сохранено в базу данных.")
        except Exception as e:
            logger.error(f"Ошибка при записи упоминания в БД: {e}", exc_info=True)

    # Отправляет уведомление в Telegram-бот
    async def notify_bot(self, message_datetime, message_link, chat_link, user_id, user_name, user_nick, message_text):
        # Преобразуем время в UTC+3 (МСК+0)
        msk_time = message_datetime + timedelta(hours=3)

        # Формируем текст уведомления
        notification_text = (
            f"➤ <b>Новое упоминание в Telegram</b>\n"
            f"⌚ <b>Время:</b> {msk_time.strftime('%d.%m.%Y %H:%M:%S')} (МСК)\n"
            f"⛓ <b>Ссылка на чат:</b> <a href=\"{chat_link}\">{chat_link}</a>\n"
            f"🔗 <b>Ссылка на сообщение:</b> <a href=\"{message_link}\">{message_link}</a>\n"
            f"👤 <b>ID пользователя:</b> <code>{user_id}</code>\n"
            f"🪪 <b>Username:</b> @{user_name if user_name else 'нет'}\n"
            f"📛 <b>Имя:</b> {user_nick}\n"
            f"💬 <b>Текст:</b> {html.escape(message_text)}"
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
async def main():
    telegram_eye = None  # Явная инициализация
    try:
        config = load_config()
        API_ID = config['api_id']
        API_HASH = config['api_hash']
        PHONE = config['phone']
        BOT_TOKEN = config['bot_token']
        APPROVED_USERS = config['approved_users']
        KEYWORDS = config['keywords']

        # Инициализация клиента
        telegram_eye = TelegramEye(API_ID, API_HASH, PHONE, KEYWORDS, BOT_TOKEN, APPROVED_USERS)
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

if __name__ == "__main__":
    asyncio.run(main())
