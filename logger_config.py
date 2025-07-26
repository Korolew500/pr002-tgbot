import logging
from logging.handlers import RotatingFileHandler
import time
from pathlib import Path


# Настройка data
log_path = Path("data") / "bot.log"
log_path.parent.mkdir(exist_ok=True)


def setup_logging():
    """Настройка логирования с UTC-временем и ротацией файлов"""
    formatter = logging.Formatter(
        '[%(asctime)s UTC] %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    formatter.converter = time.gmtime  # Используем UTC время

    # Файловый обработчик (основные логи)
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=5*1024*1024,  # 5 MB
        backupCount=3,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    # Консольный обработчик (только ошибки)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.WARNING)

    # Основная настройка
    logging.basicConfig(
        level=logging.DEBUG,  # Минимальный уровень
        handlers=[file_handler, console_handler]
    )
