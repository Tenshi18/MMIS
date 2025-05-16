# Используем базовый образ Python
FROM python:3.13-slim

# Создаём рабочую директорию
WORKDIR /app

# Копируем файлы проекта
COPY app /app

# Устанавливаем зависимости Python
RUN pip install --upgarde pip
RUN pip install --no-cache-dir -r requirements.txt

# Устанавливаем точку входа
CMD ["python", "entrypoint.py"]
