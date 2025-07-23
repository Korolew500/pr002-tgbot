import os
import asyncio
import logging
from datetime import datetime

from dotenv import load_dotenv
from telegram import Bot, Message, Update, InputMediaPhoto, InputMediaVideo
from telegram.ext import Application, ContextTypes, MessageHandler, filters
import sqlite3

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()

# Конфигурация
SOURCE_CHANNEL_ID = os.getenv('SOURCE_CHANNEL_ID')  # ID исходного канала
TARGET_CHANNEL_ID = os.getenv('TARGET_CHANNEL_ID')  # ID целевого канала
BOT_TOKEN = os.getenv('BOT_TOKEN')  # Токен бота
DELAY_MINUTES = 20  # Задержка перед пересылкой в минутах
ADDITIONAL_TEXT = "Для заказа пишите сюда » «срок доставки такой то»"  # Дополнительный текст

# Ключевые слова для фильтрации
KEYWORDS = ["Мужской", "для мужчин", "мужчины", "унисекс"]


# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('bot_db.sqlite')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS processed_messages (
            message_id INTEGER PRIMARY KEY,
            processed_at TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()


# Проверка на ключевые слова
def contains_keywords(text: str) -> bool:
    if not text:
        return False
    text_lower = text.lower()
    return any(keyword.lower() in text_lower for keyword in KEYWORDS)


# Проверка, было ли сообщение уже обработано
def is_message_processed(message_id: int) -> bool:
    conn = sqlite3.connect('bot_db.sqlite')
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM processed_messages WHERE message_id = ?', (message_id,))
    result = cursor.fetchone() is not None
    conn.close()
    return result


# Пометить сообщение как обработанное
def mark_message_processed(message_id: int):
    conn = sqlite3.connect('bot_db.sqlite')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO processed_messages (message_id, processed_at) VALUES (?, ?)',
                   (message_id, datetime.now()))
    conn.commit()
    conn.close()


# Обработчик новых сообщений в канале
async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message: Message = update.channel_post

    # Пропускаем, если сообщение уже обработано или не содержит ключевых слов
    if is_message_processed(message.message_id) or not contains_keywords(message.caption or message.text):
        return

    # Помечаем сообщение как обработанное сразу, чтобы избежать дублирования
    mark_message_processed(message.message_id)

    logger.info(f"Новый пост для обработки: {message.message_id}")

    # Задержка перед пересылкой
    await asyncio.sleep(DELAY_MINUTES * 60)

    try:
        # Пересылаем сообщение с добавлением текста
        await forward_post(message, context.bot)
    except Exception as e:
        logger.error(f"Ошибка при пересылке сообщения {message.message_id}: {e}")


# Функция пересылки поста
async def forward_post(message: Message, bot: Bot):
    # Подготовка медиа (если есть)
    media_group = []
    if message.photo:
        media_group.append(InputMediaPhoto(media=message.photo[-1].file_id, caption=prepare_caption(message)))
    elif message.video:
        media_group.append(InputMediaVideo(media=message.video.file_id, caption=prepare_caption(message)))

    # Отправляем медиагруппу или просто текст
    if media_group:
        await bot.send_media_group(chat_id=TARGET_CHANNEL_ID, media=media_group)
    elif message.text:
        await bot.send_message(chat_id=TARGET_CHANNEL_ID, text=prepare_caption(message))

    logger.info(f"Сообщение {message.message_id} успешно переслано")


# Подготовка текста с дополнительным сообщением
def prepare_caption(message: Message) -> str:
    original_caption = message.caption or message.text or ""
    return f"{original_caption}\n\n{ADDITIONAL_TEXT}"


def main():
    # Инициализация базы данных
    init_db()

    # Создание и запуск бота
    application = Application.builder().token(BOT_TOKEN).build()

    # Обработчик новых сообщений в канале
    application.add_handler(MessageHandler(filters.Chat(int(SOURCE_CHANNEL_ID)) & filters.ALL, handle_channel_post))

    # Запуск бота
    application.run_polling()


if __name__ == '__main__':
    main()
