FROM python:3.12-slim

WORKDIR /app

# 1. Копируем зависимости и устанавливаем
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Копируем ВСЁ (кроме указанного в .dockerignore)
COPY . .

CMD ["python", "main.py"]