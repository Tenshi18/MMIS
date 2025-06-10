import signal
import asyncio
import json
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message

# Настройка логирования
logger = logging.getLogger("telegram_bot")
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

# Задачи, которые не должны быть отменены
_DO_NOT_CANCEL_TASKS: set[asyncio.Task] = set()

# Добавляет задачу в список защищённых от отмены
def protect(task: asyncio.Task) -> None:
    _DO_NOT_CANCEL_TASKS.add(task)

# Обрабатывает сигнал завершения работы
def shutdown(sig: signal.Signals) -> None:
    logger.info(f"Получен сигнал завершения {sig.name}")

    all_tasks = asyncio.all_tasks()
    tasks_to_cancel = all_tasks - _DO_NOT_CANCEL_TASKS

    for task in tasks_to_cancel:
        task.cancel()

    logger.info(f"Отменено {len(tasks_to_cancel)} из {len(all_tasks)} задач")

# Настраивает обработчики сигналов для правильного завершения
def setup_signal_handler() -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown, sig)

# Загрузка конфигурации из JSON файла
def load_config():
    with open('telegram_bot_config.json', 'r') as f:
        data = json.load(f)
    return data

# Основная задача для работы с ботом
async def bot_worker(bot: Bot, dp: Dispatcher) -> None:
    await dp.start_polling(bot)

# Главная функция для запуска бота
async def main() -> None:
    # Настраиваем обработчики сигналов
    setup_signal_handler()

    # Защищаем основную задачу
    protect(asyncio.current_task())

    # Получаем конфигурацию (API_TOKEN и список одобренных пользователей)
    config = load_config()
    TOKEN = config['api_token']
    approved_users = config['approved_users']

    # Запуск бота с использованием диспетчера
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    logger.info("Бот готов принимать уведомления от TelegramEye.")

    # Обработчик для команды /start
    @dp.message(CommandStart())
    async def command_start_handler(message: Message) -> None:
        if message.from_user.id in approved_users:
            await message.reply("Добро пожаловать в Информационную систему мониторинга упоминаний.")
            logger.info(f"Пользователь {message.from_user.id} отправил /start.")

    # Добавляем задачу для работы с ботом
    bot_task = asyncio.create_task(bot_worker(bot, dp))
    protect(bot_task)

    # Ждём завершения всех задач
    logger.info("Бот запущен. Нажмите Ctrl+C для завершения.")
    await asyncio.gather(bot_task)

if __name__ == "__main__":
    asyncio.run(main())
