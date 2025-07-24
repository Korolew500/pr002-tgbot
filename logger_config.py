# logger_config.py
import logging
from logging.handlers import RotatingFileHandler


def setup_logging():
    """Настройка логирования в файл и консоль"""
    log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Настройка файлового обработчика
    file_handler = RotatingFileHandler(
        'bot.log',
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding='utf-8'
    )
    file_handler.setFormatter(log_formatter)

    # Настройка консольного обработчика
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)

    # Основная настройка
    logging.basicConfig(
        level=logging.INFO,
        handlers=[file_handler, console_handler]
    )
