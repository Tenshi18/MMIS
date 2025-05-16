import asyncio
import logging
import getpass
import telegram_eye
import telegram_bot

logger = logging.getLogger("main")
logger.setLevel(logging.INFO)

if not logger.hasHandlers():
    handlers = [
        logging.FileHandler("telegram_module.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    for handler in handlers:
        handler.setFormatter(formatter)
        logger.addHandler(handler)

async def main():
    try:
        # Запрашиваем пароль
        password = getpass.getpass("Введите пароль для расшифровки конфигурации\n> ")
        logger.info("Пароль получен.")

        # Запускаем оба модуля одновременно через gather
        await asyncio.gather(
            telegram_eye.main(password),
            telegram_bot.main(password)
        )

    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())