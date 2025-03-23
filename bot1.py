from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler,
    CallbackQueryHandler
)
from geopy.distance import geodesic
import sqlite3
from datetime import datetime
import logging

# Настройка логов
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
TOKEN = "7984308901:AAEUVmO487YOEyWH2MJOCjN6aYQVvfwZkz0"
ADMIN_PASSWORD = "123"
MAX_DISTANCE = 100  # Допустимое расстояние в метрах
ADMIN_ID = 660579475  # Замените на ваш ID

# Состояния
USERNAME, PASSWORD, LOCATION, NAME, USER_SEARCH = range(5)

# Инициализация БД
conn = sqlite3.connect('checkins.db', check_same_thread=False)
cursor = conn.cursor()

# Создание таблиц
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT NOT NULL
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_settings (
        user_id INTEGER PRIMARY KEY,
        location_id INTEGER,
        FOREIGN KEY(location_id) REFERENCES locations(id)
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS locations (
        id INTEGER PRIMARY KEY,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        name TEXT UNIQUE NOT NULL
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS shifts (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        start_time DATETIME NOT NULL,
        end_time DATETIME,
        duration INTEGER,
        FOREIGN KEY(user_id) REFERENCES users(user_id))
''')
conn.commit()

# ---------------------- Основные функции ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Регистрация и главное меню"""
    try:
        user = update.message.from_user
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user.id,))

        if not cursor.fetchone():
            await update.message.reply_text("👤 Введите ваше ФИО:")
            return USERNAME

        buttons = [
            [KeyboardButton("📍 Начать смену", request_location=True)],
            [KeyboardButton("🌍 Выбрать локацию"), KeyboardButton("🛑 Завершить смену")],
            [KeyboardButton("📊 Моя статистика")]
        ]
        keyboard = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        await update.message.reply_text("Выберите действие:", reply_markup=keyboard)
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка в /start: {e}")
        return ConversationHandler.END

async def save_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение ФИО"""
    try:
        user = update.message.from_user
        full_name = update.message.text.strip()

        if len(full_name) < 2:
            await update.message.reply_text("❌ Введите корректное ФИО!")
            return USERNAME

        cursor.execute('''
            INSERT INTO users (user_id, username, full_name)
            VALUES (?, ?, ?)
        ''', (user.id, user.username, full_name))
        conn.commit()

        await update.message.reply_text("✅ Регистрация завершена!")
        return await start(update, context)

    except sqlite3.IntegrityError:
        await update.message.reply_text("⚠️ Вы уже зарегистрированы!")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка сохранения ФИО: {e}")
        return ConversationHandler.END

# ---------------------- Локации ----------------------
async def choose_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор рабочей локации"""
    try:
        cursor.execute("SELECT id, name FROM locations")
        locations = cursor.fetchall()

        if not locations:
            await update.message.reply_text("❌ Локации не добавлены! Обратитесь к администратору.")
            return

        buttons = [
            [InlineKeyboardButton(name, callback_data=f"loc_{id}")]
            for id, name in locations
        ]
        await update.message.reply_text(
            "📍 Выберите рабочую локацию:",
            reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        logger.error(f"Ошибка выбора локации: {e}")

async def location_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора локации"""
    try:
        query = update.callback_query
        await query.answer()
        loc_id = int(query.data.split("_")[1])
        user_id = query.from_user.id

        cursor.execute('''
            INSERT OR REPLACE INTO user_settings (user_id, location_id)
            VALUES (?, ?)
        ''', (user_id, loc_id))
        conn.commit()

        await query.edit_message_text("✅ Локация выбрана!")
    except Exception as e:
        logger.error(f"Ошибка выбора локации: {e}")

# ---------------------- Управление сменами ----------------------
async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало смены с проверкой геолокации"""
    try:
        user = update.message.from_user
        location = update.message.location

        cursor.execute('''
            SELECT l.latitude, l.longitude
            FROM user_settings us
            JOIN locations l ON us.location_id = l.id
            WHERE us.user_id = ?
        ''', (user.id,))
        office = cursor.fetchone()

        if not office:
            await update.message.reply_text("❌ Сначала выберите локацию!")
            return

        user_coords = (location.latitude, location.longitude)
        distance = geodesic(user_coords, office).meters

        if distance > MAX_DISTANCE:
            await update.message.reply_text(f"❌ Вы в {distance:.0f} м от объекта!")
            return

        cursor.execute('''
            INSERT INTO shifts (user_id, start_time)
            VALUES (?, ?)
        ''', (user.id, datetime.now()))
        conn.commit()
        await update.message.reply_text("✅ Смена начата!")

    except Exception as e:
        logger.error(f"Ошибка начала смены: {e}")

async def end_shift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершение смены"""
    try:
        user = update.message.from_user

        cursor.execute('''
            SELECT id, start_time
            FROM shifts
            WHERE user_id = ? AND end_time IS NULL
        ''', (user.id,))
        shift = cursor.fetchone()

        if not shift:
            await update.message.reply_text("❌ Нет активной смены!")
            return

        end_time = datetime.now()
        start_time = datetime.strptime(shift[1], "%Y-%m-%d %H:%M:%S.%f")
        duration = int((end_time - start_time).total_seconds())

        cursor.execute('''
            UPDATE shifts
            SET end_time = ?, duration = ?
            WHERE id = ?
        ''', (end_time, duration, shift[0]))
        conn.commit()

        hours = duration // 3600
        minutes = (duration % 3600) // 60
        await update.message.reply_text(f"🛑 Смена завершена!\n⏱ Время работы: {hours} ч {minutes} мин")

    except Exception as e:
        logger.error(f"Ошибка завершения смены: {e}")

# ---------------------- Статистика ----------------------
async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Личная статистика сотрудника"""
    try:
        user = update.message.from_user

        cursor.execute('''
            SELECT SUM(duration)
            FROM shifts
            WHERE user_id = ?
        ''', (user.id,))
        total_seconds = cursor.fetchone()[0] or 0

        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        await update.message.reply_text(f"📊 Ваше общее время работы: {hours} ч {minutes} мин")

    except Exception as e:
        logger.error(f"Ошибка статистики: {e}")

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Полная статистика для админа"""
    try:
        if update.message.from_user.id != ADMIN_ID:
            await update.message.reply_text("⛔ Доступ запрещен!")
            return

        cursor.execute('''
            SELECT
                u.full_name,
                s.start_time,
                s.end_time,
                s.duration
            FROM shifts s
            JOIN users u ON s.user_id = u.user_id
            ORDER BY s.start_time DESC
        ''')

        report = "📈 Статистика сотрудников:\n\n"
        for row in cursor.fetchall():
            start_time = datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S.%f").strftime("%d.%m %H:%M")
            end_time = datetime.strptime(row[2], "%Y-%m-%d %H:%M:%S.%f").strftime("%d.%m %H:%M") if row[2] else "❌ Не завершена"
            hours = row[3] // 3600 if row[3] else 0
            minutes = (row[3] % 3600) // 60 if row[3] else 0
            report += f"👤 {row[0]}\n🕒 {start_time} – {end_time}\n⏱ {hours} ч {minutes} м\n\n"

        await update.message.reply_text(report or "❌ Данных нет")

    except Exception as e:
        logger.error(f"Ошибка админ-статистики: {e}")

# ---------------------- Поиск по сотрудникам ----------------------
async def user_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск статистики по сотруднику"""
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещен!")
        return ConversationHandler.END

    await update.message.reply_text("🔍 Введите фамилию сотрудника:")
    return USER_SEARCH

async def show_user_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальная статистика по сменам сотрудника"""
    try:
        last_name = update.message.text.strip()
        logger.info(f"Поиск сотрудника: {last_name}")

        cursor.execute('''
            SELECT
                u.user_id,
                u.full_name,
                s.id,
                s.start_time,
                s.end_time,
                s.duration
            FROM users u
            LEFT JOIN shifts s ON u.user_id = s.user_id
            WHERE u.full_name LIKE ?
            ORDER BY s.start_time DESC
        ''', (f'%{last_name}%',))

        results = cursor.fetchall()
        logger.info(f"Найдено записей: {len(results)}")

        if not results:
            await update.message.reply_text("❌ Сотрудники не найдены!")
            return ConversationHandler.END

        report = []
        current_user = None
        total_shifts = 0
        total_duration = 0

        for row in results:
            user_id, full_name, shift_id, start_time, end_time, duration = row
            duration = duration or 0  # Обработка NULL

            if current_user != user_id:
                if current_user is not None:
                    # Итоги предыдущего сотрудника
                    hours_total = total_duration // 3600
                    minutes_total = (total_duration % 3600) // 60
                    report.append(f"▫️ Всего смен: {total_shifts}\n▫️ Общее время: {hours_total} ч {minutes_total} м\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n")

                current_user = user_id
                total_shifts = 0
                total_duration = 0
                report.append(f"👤 *{full_name}* (ID: {user_id})\n")

            if shift_id:
                # Форматирование времени
                try:
                    start_str = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S.%f").strftime("%d.%m %H:%M")
                    end_str = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S.%f").strftime("%d.%m %H:%M") if end_time else "Не завершена"
                except:
                    start_str = "Ошибка формата"
                    end_str = "Ошибка формата"

                hours = duration // 3600
                minutes = (duration % 3600) // 60

                report.append(
                    f"📅 Смена #{shift_id}\n"
                    f"🕒 Начало: {start_str}\n"
                    f"🕒 Окончание: {end_str}\n"
                    f"⏱ Длительность: {hours} ч {minutes} м\n"
                    f"――――――――――――――――――\n"
                )
                total_shifts += 1
                total_duration += duration

        # Добавить итоги последнего сотрудника
        if current_user is not None:
            hours_total = total_duration // 3600
            minutes_total = (total_duration % 3600) // 60
            report.append(f"▫️ Всего смен: {total_shifts}\n▫️ Общее время: {hours_total} ч {minutes_total} м\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n")

        full_report = "".join(report)
        if len(full_report) > 4096:
            for part in [full_report[i:i+4096] for i in range(0, len(full_report), 4096)]:
                await update.message.reply_markdown(part)
        else:
            await update.message.reply_markdown(full_report)

        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка: {str(e)}", exc_info=True)
        await update.message.reply_text("⚠️ Ошибка при обработке запроса")
        return ConversationHandler.END

# ---------------------- Админ-панель ----------------------
async def add_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление локации"""
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещен!")
        return ConversationHandler.END

    await update.message.reply_text("🔐 Введите пароль администратора:")
    return PASSWORD

async def check_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка пароля"""
    if update.message.text != ADMIN_PASSWORD:
        await update.message.reply_text("❌ Неверный пароль!")
        return ConversationHandler.END

    await update.message.reply_text("📌 Отправьте геолокацию объекта:")
    return LOCATION

async def save_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение геолокации"""
    context.user_data['lat'] = update.message.location.latitude
    context.user_data['lon'] = update.message.location.longitude
    await update.message.reply_text("📝 Введите название локации:")
    return NAME

async def save_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение названия локации"""
    try:
        name = update.message.text.strip()
        lat = context.user_data['lat']
        lon = context.user_data['lon']

        if len(name) < 2:
            await update.message.reply_text("❌ Название слишком короткое!")
            return NAME

        cursor.execute('''
            INSERT INTO locations (latitude, longitude, name)
            VALUES (?, ?, ?)
        ''', (lat, lon, name))
        conn.commit()
        await update.message.reply_text(f"✅ Локация '{name}' добавлена!")
        return ConversationHandler.END

    except sqlite3.IntegrityError:
        await update.message.reply_text("❌ Локация с таким именем уже существует!")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка сохранения названия: {e}")
        return ConversationHandler.END

# ---------------------- Запуск ----------------------
def main():
    app = Application.builder().token(TOKEN).build()

    # Обработчики
    user_stats_handler = ConversationHandler(
        entry_points=[CommandHandler('user_stats', user_stats)],
        states={
            USER_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, show_user_stats)]
        },
        fallbacks=[]
    )

    reg_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            USERNAME: [MessageHandler(filters.TEXT, save_username)]
        },
        fallbacks=[]
    )

    add_loc_handler = ConversationHandler(
        entry_points=[CommandHandler('add', add_location)],
        states={
            PASSWORD: [MessageHandler(filters.TEXT, check_password)],
            LOCATION: [MessageHandler(filters.LOCATION, save_location)],
            NAME: [MessageHandler(filters.TEXT, save_name)]
        },
        fallbacks=[]
    )

    # Регистрация обработчиков (ВАЖНО: user_stats_handler первый!)
    app.add_handler(user_stats_handler)
    app.add_handler(reg_handler)
    app.add_handler(add_loc_handler)
    app.add_handler(CommandHandler("admin_stats", admin_stats))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.Regex(r"🌍 Выбрать локацию"), choose_location))
    app.add_handler(MessageHandler(filters.Regex(r"🛑 Завершить смену"), end_shift))
    app.add_handler(MessageHandler(filters.Regex(r"📊 Моя статистика"), show_stats))
    app.add_handler(CallbackQueryHandler(location_selected, pattern=r"^loc_"))

    logger.info("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()