import os
import asyncio
import sys
from typing import Dict, List
from datetime import datetime
from dotenv import load_dotenv
from telegram import Bot, Update, Message, InputMediaPhoto, InputMediaVideo, InputMediaDocument
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import logging
from logger_config import setup_logging
import sqlite3
import json

# Настройка логирования
setup_logging()
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
SOURCE_CHANNEL_ID = int(os.getenv("SOURCE_CHANNEL_ID"))
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID"))

# Ключевые слова для фильтрации
KEYWORDS = ["мужской", "для мужчин", "мужчины", "унисекс", "унисекс"]

# Дополнительный текст для постов
ADDITIONAL_TEXT = "\n\nДля заказа пишите сюда » срок доставки: 2-3 дня"


# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('posts.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_message_id INTEGER,
            media_group_id TEXT,
            file_ids TEXT,
            caption TEXT,
            post_date TEXT,
            is_processed INTEGER DEFAULT 0,
            forwarded_message_id INTEGER
        )
    ''')
    conn.commit()
    conn.close()


init_db()


class PostManager:
    @staticmethod
    def _get_connection():
        """Создает и возвращает соединение с базой данных"""
        return sqlite3.connect('posts.db')

    @staticmethod
    def clear_db():
        """Очищает базу данных (только для тестов!)"""
        try:
            conn = sqlite3.connect('posts.db')
            cursor = conn.cursor()
            cursor.execute('DELETE FROM posts')
            conn.commit()
            logger.warning("База данных очищена!")
        except Exception as e:
            logger.error(f"Ошибка очистки БД: {e}")
        finally:
            if conn:
                conn.close()

    @staticmethod
    def save_post(message: Message):
        """Сохраняет пост в базу данных"""
        conn = None
        try:
            conn = sqlite3.connect('posts.db')
            cursor = conn.cursor()

            media_group_id = message.media_group_id or str(message.message_id)

            # Получаем file_id для текущего медиа
            file_id = None
            file_type = None  # Добавляем переменную для типа файла

            if message.photo:
                file_id = message.photo[-1].file_id
                file_type = 'photo'
            elif message.video:
                file_id = message.video.file_id
                file_type = 'video'
            elif message.document:
                file_id = message.document.file_id
                file_type = 'document'
            elif message.audio:
                file_id = message.audio.file_id
                file_type = 'audio'

            # Для медиагрупп сохраняем caption только из первого сообщения
            caption = None
            if not message.media_group_id or (message.caption or message.text):
                caption = message.caption if message.caption else ""
                if message.text and not message.caption:
                    caption = message.text

            # Проверяем существующую запись
            cursor.execute('SELECT file_ids, caption FROM posts WHERE media_group_id = ?', (media_group_id,))
            existing = cursor.fetchone()

            if existing:
                # Обновляем существующую запись
                existing_file_ids = json.loads(existing[0]) if existing[0] else []
                existing_caption = existing[1] if existing[1] else ""

                if file_id and file_id not in existing_file_ids:
                    existing_file_ids.append(file_id)

                # Обновляем caption только если его еще нет
                update_caption = existing_caption if existing_caption else caption
                cursor.execute('''
                    UPDATE posts 
                    SET file_ids = ?, caption = ?
                    WHERE media_group_id = ?
                ''', (json.dumps(existing_file_ids), update_caption, media_group_id))
            else:
                # Создаем новую запись
                file_ids = [file_id] if file_id else []
                cursor.execute('''
                    INSERT INTO posts 
                    (original_message_id, media_group_id, file_ids, caption, post_date)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    message.message_id,
                    media_group_id,
                    json.dumps(file_ids),
                    caption,
                    datetime.now().isoformat()
                ))

            conn.commit()
            logger.info(
                f"Сохранен пост {message.message_id}, группа {media_group_id}, файлов: {len(file_ids) if 'file_ids' in locals() else 1}, caption: '{caption}'")

        except Exception as e:
            logger.error(f"Ошибка сохранения поста {message.message_id}: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    @staticmethod
    def get_unprocessed_posts() -> List[Dict]:
        """Возвращает необработанные посты"""
        try:
            conn = PostManager._get_connection()
            cursor = conn.cursor()

            cursor.execute('''
                SELECT 
                    media_group_id,
                    file_ids,
                    caption,
                    post_date
                FROM posts
                WHERE is_processed = 0
                ORDER BY post_date ASC
            ''')

            posts = []
            for row in cursor.fetchall():
                media_group_id, file_ids_json, caption, post_date = row
                try:
                    file_ids = json.loads(file_ids_json) if file_ids_json else []
                except json.JSONDecodeError:
                    file_ids = []

                posts.append({
                    'media_group_id': media_group_id,
                    'file_ids': file_ids,
                    'caption': caption if caption else "",
                    'post_date': post_date
                })

            return posts

        except Exception as e:
            logger.error(f"Ошибка при получении постов: {e}", exc_info=True)
            return []
        finally:
            if conn:
                conn.close()

    @staticmethod
    def mark_as_processed(media_group_id: str, forwarded_message_id: int):
        """Помечает пост как обработанный"""
        conn = None
        try:
            conn = PostManager._get_connection()
            cursor = conn.cursor()

            cursor.execute('''
                UPDATE posts
                SET is_processed = 1, forwarded_message_id = ?
                WHERE media_group_id = ? AND is_processed = 0
            ''', (forwarded_message_id, media_group_id))

            conn.commit()
            logger.info(f"Пост {media_group_id} помечен как обработанный")

        except Exception as e:
            logger.error(f"Ошибка при обновлении поста: {e}", exc_info=True)
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    @staticmethod
    def debug_db():
        """Выводит содержимое базы данных для отладки"""
        conn = None
        try:
            conn = PostManager._get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM posts")
            rows = cursor.fetchall()

            logger.info("Текущее содержимое базы данных:")
            for row in rows:
                logger.info(row)

        except Exception as e:
            logger.error(f"Ошибка при чтении базы данных: {e}")
        finally:
            if conn:
                conn.close()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик входящих сообщений"""
    try:
        message = update.effective_message

        if message.chat.id != SOURCE_CHANNEL_ID:
            return

        # Для медиагрупп - обрабатываем все сообщения, даже без ключевых слов
        if message.media_group_id:
            logger.info(f"Получено сообщение медиагруппы: {message.message_id}")
            PostManager.save_post(message)
            return

        # Для обычных сообщений проверяем ключевые слова
        has_keyword = False
        if message.caption and any(keyword.lower() in message.caption.lower() for keyword in KEYWORDS):
            has_keyword = True
        elif message.text and any(keyword.lower() in message.text.lower() for keyword in KEYWORDS):
            has_keyword = True

        if has_keyword:
            logger.info(f"Найден пост с ключевым словом: {message.message_id}")
            PostManager.save_post(message)
        else:
            logger.info("Ключевые слова не найдены, пропускаем сообщение")

    except Exception as e:
        logger.error(f"Ошибка в handle_message: {e}", exc_info=True)


async def process_pending_posts(app: Application):
    """Периодическая задача для обработки отложенных постов"""
    try:
        logger.info("Запуск проверки отложенных постов...")
        unprocessed_posts = PostManager.get_unprocessed_posts()

        # Группируем по media_group_id
        grouped_posts = {}
        for post in unprocessed_posts:
            if post['media_group_id'] not in grouped_posts:
                grouped_posts[post['media_group_id']] = []
            grouped_posts[post['media_group_id']].append(post)

        logger.info(f"Найдено {len(grouped_posts)} групп постов для обработки")

        bot = app.bot

        for media_group_id, posts in grouped_posts.items():
            try:
                # Берем первый пост группы для получения caption
                main_post = posts[0]
                original_caption = main_post['caption'] or ""

                # Формируем полную подпись
                full_caption = f"{original_caption}\n\n{ADDITIONAL_TEXT}" if original_caption else ADDITIONAL_TEXT

                # Собираем все file_ids из группы
                all_file_ids = []
                for post in posts:
                    all_file_ids.extend(post['file_ids'])

                logger.info(f"Обработка группы {media_group_id}, оригинальный текст: '{original_caption}'")

                # Текстовое сообщение
                if not all_file_ids:
                    msg = await bot.send_message(
                        chat_id=TARGET_CHANNEL_ID,
                        text=full_caption
                    )
                # Одиночное медиа
                # Одиночное медиа
                elif len(all_file_ids) == 1:
                    msg = None  # Инициализируем переменную
                    try:
                        file_id = all_file_ids[0]
                        if file_id.startswith('AgAC'):  # Фото
                            msg = await bot.send_photo(
                                chat_id=TARGET_CHANNEL_ID,
                                photo=file_id,
                                caption=full_caption,
                                parse_mode="Markdown"
                            )
                        elif file_id.startswith('BAAC'):  # Видео
                            msg = await bot.send_video(
                                chat_id=TARGET_CHANNEL_ID,
                                video=file_id,
                                caption=full_caption,
                                parse_mode="Markdown"
                            )
                        elif file_id.startswith('BQAC'):  # Документы
                            msg = await bot.send_document(
                                chat_id=TARGET_CHANNEL_ID,
                                document=file_id,
                                caption=full_caption,
                                parse_mode="Markdown"
                            )
                        elif file_id.startswith('CQAC'):  # Аудио
                            msg = await bot.send_audio(
                                chat_id=TARGET_CHANNEL_ID,
                                audio=file_id,
                                caption=full_caption,
                                parse_mode="Markdown"
                            )

                        if msg:
                            PostManager.mark_as_processed(media_group_id, msg.message_id)
                            logger.info(f"Пост {media_group_id} успешно переслан")
                        else:
                            logger.warning(f"Не удалось отправить файл {file_id[:10]}...")

                    except Exception as e:
                        file_id = all_file_ids[0]
                        logger.error(f"Ошибка отправки файла {file_id[:10] if file_id else 'unknown'}: {e}")

                # Медиагруппа
                else:
                    media_group = []
                    for i, file_id in enumerate(all_file_ids):
                        if file_id.startswith('AgAC'):  # Фото
                            media = InputMediaPhoto(
                                media=file_id,
                                caption=full_caption if i == 0 else None,
                                parse_mode="Markdown"
                            )
                        elif file_id.startswith('BAAC'):  # Видео
                            media = InputMediaVideo(
                                media=file_id,
                                caption=full_caption if i == 0 else None,
                                parse_mode="Markdown"
                            )
                        elif file_id.startswith('BQAC'):  # Документы
                            media = InputMediaDocument(
                                media=file_id,
                                caption=full_caption if i == 0 else None,
                                parse_mode="Markdown"
                            )
                        else:
                            continue  # Пропускаем аудио и неизвестные типы

                        media_group.append(media)

                    if media_group:
                        try:
                            messages = await bot.send_media_group(
                                chat_id=TARGET_CHANNEL_ID,
                                media=media_group
                            )
                            msg = messages[0] if messages else None
                        except Exception as e:
                            logger.error(f"Ошибка отправки медиагруппы: {e}")

                if msg:
                    try:
                        if 'msg' in locals():
                            PostManager.mark_as_processed(media_group_id, msg.message_id)
                            logger.info(f"Пост {media_group_id} успешно переслан")
                        else:
                            logger.error("Сообщение не было отправлено")
                    except Exception as e:
                        logger.error(f"Ошибка при пометке поста: {e}")
                    logger.info(f"Группа {media_group_id} успешно переслана")
                else:
                    logger.error(f"Не удалось отправить группу {media_group_id}")

            except Exception as e:
                logger.error(f"Ошибка пересылки группы {media_group_id}: {e}")

    except Exception as e:
        logger.error(f"Ошибка process_pending_posts: {e}")


async def run_bot():
    """Основная асинхронная функция для запуска бота"""
    # Для Windows
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    app = None
    periodic_task = None

    try:
        app = Application.builder().token(BOT_TOKEN).build()

        # Добавляем обработчик сообщений
        app.add_handler(MessageHandler(
            filters.Chat(chat_id=SOURCE_CHANNEL_ID) & (
                    filters.PHOTO | filters.VIDEO | filters.Document.ALL |
                    filters.AUDIO | filters.CAPTION | filters.TEXT
            ),
            handle_message
        ))

        # Инициализируем приложение перед запуском
        await app.initialize()

        # Создаем фоновую задачу
        periodic_task = asyncio.create_task(run_periodic_check(app))

        logger.info("Бот запущен")
        await app.start()
        await app.updater.start_polling()

        # Бесконечный цикл, пока бот работает
        while True:
            await asyncio.sleep(1)

    except asyncio.CancelledError:
        logger.info("Получен сигнал на завершение работы")
    except Exception as e:
        logger.error(f"Ошибка при работе бота: {e}", exc_info=True)
    finally:
        # Корректное завершение
        if periodic_task:
            periodic_task.cancel()
            try:
                await periodic_task
            except asyncio.CancelledError:
                pass

        if app:
            try:
                await app.updater.stop()
                await app.stop()
                await app.shutdown()
            except Exception as e:
                logger.error(f"Ошибка при остановке бота: {e}")

        logger.info("Бот полностью остановлен")


async def run_periodic_check(app: Application):
    """Фоновая задача с периодической проверкой"""
    while True:
        try:
            await process_pending_posts(app)
            await asyncio.sleep(10)  # Интервал проверки (10 секунд)
        except asyncio.CancelledError:
            logger.info("Периодическая проверка остановлена")
            break
        except Exception as e:
            logger.error(f"Ошибка в периодической проверке: {e}")
            await asyncio.sleep(5)  # Задержка при ошибке


@staticmethod
def check_media_groups():
    """Проверяет целостность медиагрупп в базе"""
    try:
        conn = sqlite3.connect('posts.db')
        cursor = conn.cursor()

        cursor.execute('''
            SELECT media_group_id, COUNT(*) as cnt 
            FROM posts 
            WHERE media_group_id NOT LIKE '%-%' 
            GROUP BY media_group_id 
            HAVING cnt > 1
        ''')

        groups = cursor.fetchall()
        logger.info(f"Найдено {len(groups)} медиагрупп в базе:")
        for group_id, count in groups:
            logger.info(f"Группа {group_id}: {count} элементов")

    except Exception as e:
        logger.error(f"Ошибка проверки медиагрупп: {e}")
    finally:
        if conn:
            conn.close()


def main():
    """Точка входа"""
    PostManager.clear_db()
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Бот остановлен по запросу пользователя")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
    finally:
        logging.shutdown()


if __name__ == "__main__":
    main()
