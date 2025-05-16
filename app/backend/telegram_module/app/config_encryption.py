import logging
import getpass
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.padding import PKCS7
import os
import json

# Настройка логирования
logger = logging.getLogger("config_encryption")
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

# Генерация ключа на основе пароля
def generate_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend()
    )
    return kdf.derive(password.encode())

# Функция шифрования
def encrypt_file(input_file: str, output_file: str, password: str):
    salt = os.urandom(16)  # Генерируем соль
    key = generate_key(password, salt)
    iv = os.urandom(16)  # Генерируем вектор инициализации
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    padder = PKCS7(algorithms.AES.block_size).padder()

    with open(input_file, 'rb') as f:
        plaintext = f.read()

    padded_data = padder.update(plaintext) + padder.finalize()
    ciphertext = encryptor.update(padded_data) + encryptor.finalize()

    with open(output_file, 'wb') as f:
        f.write(salt + iv + ciphertext)  # Сохраняем соль, IV и шифротекст

    logger.info(f"Файл {input_file} успешно зашифрован в {output_file}")

# Функция дешифрования
def decrypt_file(input_file: str, output_file: str, password: str):
    with open(input_file, 'rb') as f:
        data = f.read()

    salt = data[:16]  # Извлекаем соль
    iv = data[16:32]  # Извлекаем IV
    ciphertext = data[32:]  # Извлекаем шифротекст

    key = generate_key(password, salt)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    unpadder = PKCS7(algorithms.AES.block_size).unpadder()

    padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()

    with open(output_file, 'wb') as f:
        f.write(plaintext)

    logger.info(f"Файл {input_file} успешно расшифрован в {output_file}")

# Чтение конфигурации из зашифрованного файла
def read_encrypted_config(input_file: str, password: str) -> dict:
    temp_file = "temp_config.json"
    decrypt_file(input_file, temp_file, password)
    with open(temp_file, 'r') as f:
        config = json.load(f)
    os.remove(temp_file)
    logger.info(f"Конфигурация успешно прочитана из {input_file}")
    return config

# Проверка и шифрование JSON, если зашифрованный файл отсутствует
def check_and_encrypt(input_file: str, encrypted_file: str, password: str):
    if not os.path.exists(encrypted_file):
        logger.warning(f"Зашифрованный файл {encrypted_file} не найден. Выполняется шифрование...")
        encrypt_file(input_file, encrypted_file, password)
        os.remove(input_file)
        logger.info(f"Исходный файл {input_file} удалён после шифрования.")
    else:
        logger.info(f"Зашифрованный файл {encrypted_file} уже существует.")

# Функция смены пароля
def change_password(input_file: str, output_file: str, old_password: str, new_password: str):
    logger.info(f"Начинаю процедуру смены пароля для файла {input_file}.")

    # Расшифровываем файл во временный файл
    temp_file = "temp_config.json"
    try:
        decrypt_file(input_file, temp_file, old_password)
    except Exception as e:
        logger.error(f"Ошибка при расшифровке файла {input_file}: {e}")
        return

    # Шифруем временный файл с новым паролем
    try:
        encrypt_file(temp_file, output_file, new_password)
        logger.info(f"Пароль успешно изменён для файла {input_file}. Новый файл сохранён как {output_file}.")
    except Exception as e:
        logger.error(f"Ошибка при шифровании файла {temp_file}: {e}")
    finally:
        # Удаляем временный файл
        if os.path.exists(temp_file):
            os.remove(temp_file)
            logger.debug(f"Временный файл {temp_file} удалён.")

# if __name__ == "__main__":
#     old_password = getpass.getpass("Введите текущий пароль: ")
#     new_password = getpass.getpass("Введите новый пароль: ")
#
#     change_password("telegram_eye_config.json.enc", "telegram_eye_config.json.enc", old_password, new_password)
#     change_password("telegram_bot_config.json.enc", "telegram_bot_config.json.enc", old_password, new_password)