import asyncio
import sqlite3
from datetime import datetime, date, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

BOT_TOKEN = "8391960299:AAEULi1OufqmcO9jSRa1RQMGslMnDfP0yU0"

# ТВОЙ Telegram ID (админ)
OWNER_ID = 1073943137

# ID девушки — как только она напишет боту, посмотри в логах и подставь сюда
GIRL_ID = 1886767965

DB_PATH = "bot.db"


def db():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        difficulty INTEGER NOT NULL,
        active INTEGER NOT NULL DEFAULT 1
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_stats (
        user_id INTEGER PRIMARY KEY,
        points INTEGER NOT NULL DEFAULT 0,
        completed_tasks INTEGER NOT NULL DEFAULT 0,
        current_streak INTEGER NOT NULL DEFAULT 0,
        last_done_date TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS completions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        task_id INTEGER NOT NULL,
        points INTEGER NOT NULL,
        done_at TEXT NOT NULL
    );
    """)

    conn.commit()
    conn.close()


def get_or_create_stats(user_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT user_id, points, completed_tasks, current_streak, last_done_date FROM user_stats WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if row is None:
        cur.execute("INSERT INTO user_stats(user_id) VALUES (?)", (user_id,))
        conn.commit()
        cur.execute("SELECT user_id, points, completed_tasks, current_streak, last_done_date FROM user_stats WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
    conn.close()
    return row


def update_streak_and_points(user_id: int, task_id: int, difficulty: int):
    """Обновляем очки, серию и записываем выполнение."""
    conn = db()
    cur = conn.cursor()

    today = date.today()
    today_str = today.isoformat()

    cur.execute("SELECT points, completed_tasks, current_streak, last_done_date FROM user_stats WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if row is None:
        points = 0
        completed = 0
        streak = 0
        last_done_date = None
    else:
        points, completed, streak, last_done_date = row

    # обновляем серию (streak)
    if last_done_date is None:
        # первое выполнение
        streak = 1
    else:
        last_date = date.fromisoformat(last_done_date)
        if today == last_date:
            # сегодня уже что-то делала — серию не трогаем
            pass
        elif today == last_date + timedelta(days=1):
            # +1 день подряд
            streak += 1
        else:
            # серия оборвалась
            streak = 1

    points += difficulty
    completed += 1

    # обновляем user_stats
    cur.execute("""
        INSERT INTO user_stats (user_id, points, completed_tasks, current_streak, last_done_date)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            points = ?,
            completed_tasks = ?,
            current_streak = ?,
            last_done_date = ?;
    """, (
        user_id, points, completed, streak, today_str,
        points, completed, streak, today_str
    ))

    # пишем в историю
    cur.execute("""
        INSERT INTO completions (user_id, task_id, points, done_at)
        VALUES (?, ?, ?, ?);
    """, (user_id, task_id, difficulty, datetime.now().isoformat()))

    conn.commit()
    conn.close()

    return points, streak


def difficulty_to_label(diff: int) -> str:
    if diff == 1:
        return "Нормальная (1)"
    elif diff == 3:
        return "Сложная (3)"
    elif diff == 5:
        return "Суперсложная (5)"
    return f"{diff} очков"


dp = Dispatcher()

# временный кэш для добавления задач: {user_id: "текст задания"}
pending_task_text = {}


@dp.message(Command("start"))
async def cmd_start(message: Message):
    if message.from_user.id == OWNER_ID:
        await message.answer(
            "Привет, босс! 🧹\n\n"
            "Команды:\n"
            "/add_task – добавить задание\n"
            "/list_tasks – список заданий\n"
            "/stats – статистика девушки\n"
            "/remind – отправить напоминание по id задачи"
        )
    elif message.from_user.id == GIRL_ID:
        await message.answer(
            "Привет! 🫶\n"
            "Здесь будут появляться задания по дому. За выполнение ты получаешь очки и растишь 🔥 серию.\n\n"
            "Команды:\n"
            "/tasks – мои задания\n"
            "/stats – моя статистика"
        )
    else:
        await message.answer("Этот бот приватный, доступ только для вас двоих 😎")


# ---------- АДМИН: ДОБАВИТЬ ЗАДАНИЕ ----------

@dp.message(Command("add_task"))
async def cmd_add_task(message: Message):
    if message.from_user.id != OWNER_ID:
        return
    await message.answer("Напиши текст задания, которое хочешь добавить.")
    pending_task_text[message.from_user.id] = "__WAIT_TEXT__"


@dp.message(F.text & F.from_user.id == OWNER_ID)
async def process_task_text(message: Message):
    # если мы ждём текст задания
    if pending_task_text.get(message.from_user.id) == "__WAIT_TEXT__":
        text = message.text.strip()
        if not text:
            await message.answer("Текст пустой, напиши нормальное задание 🙂")
            return

        pending_task_text[message.from_user.id] = text

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Нормальное (1)", callback_data="add_diff_1"),
                    InlineKeyboardButton(text="Сложное (3)", callback_data="add_diff_3"),
                    InlineKeyboardButton(text="Суперсложное (5)", callback_data="add_diff_5"),
                ]
            ]
        )
        await message.answer(
            f"Окей, задание:\n\n<b>{text}</b>\n\nВыбери сложность:",
            reply_markup=kb
        )


@dp.callback_query(F.data.startswith("add_diff_"))
async def callback_add_task_diff(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("Не для тебя 😉", show_alert=True)
        return

    diff = int(callback.data.split("_")[-1])
    text = pending_task_text.get(callback.from_user.id)

    if not text or text == "__WAIT_TEXT__":
        await callback.answer("Текст задания потерян, попробуй ещё раз через /add_task", show_alert=True)
        return

    conn = db()
    cur = conn.cursor()
    cur.execute("INSERT INTO tasks (title, difficulty) VALUES (?, ?)", (text, diff))
    conn.commit()
    task_id = cur.lastrowid
    conn.close()

    # очистим кэш
    pending_task_text.pop(callback.from_user.id, None)

    await callback.message.edit_text(
        f"✅ Задание добавлено!\n\n"
        f"ID: <code>{task_id}</code>\n"
        f"Текст: <b>{text}</b>\n"
        f"Сложность: {difficulty_to_label(diff)}"
    )
    await callback.answer()


# ---------- СПИСОК ЗАДАЧ ДЛЯ ДЕВУШКИ ----------

@dp.message(Command("tasks"))
async def cmd_tasks(message: Message):
    if message.from_user.id != GIRL_ID:
        await message.answer("Эта команда для твоей девушки 💅")
        return

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id, title, difficulty FROM tasks WHERE active = 1 ORDER BY id;")
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await message.answer("Пока нет активных заданий. Посмотри строго на своего мужчину 😏")
        return

    for task_id, title, diff in rows:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Сделано", callback_data=f"done_{task_id}")]
            ]
        )
        await message.answer(
            f"Задание <b>#{task_id}</b>\n"
            f"{title}\n\n"
            f"Сложность: {difficulty_to_label(diff)}",
            reply_markup=kb
        )


# ---------- ВЫПОЛНЕНИЕ ЗАДАНИЯ ----------

@dp.callback_query(F.data.startswith("done_"))
async def callback_task_done(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != GIRL_ID:
        await callback.answer("Только она может отмечать выполнение 🔥", show_alert=True)
        return

    task_id = int(callback.data.split("_")[-1])

    # 1) Берём задание из базы
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT title, difficulty FROM tasks WHERE id = ? AND active = 1", (task_id,))
    row = cur.fetchone()

    if not row:
        conn.close()
        await callback.answer("Задание уже неактивно или не найдено.", show_alert=True)
        return

    title, diff = row

    # 2) Сразу удаляем задание, чтобы его нельзя было выполнить повторно
    cur.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()

    # 3) Обновляем очки и серию (внутри функции откроется своя БД-сессия)
    total_points, streak = update_streak_and_points(callback.from_user.id, task_id, diff)

    # 4) Обновляем сообщение у неё
    await callback.message.edit_text(
        f"✅ Задание #{task_id} выполнено и снято с доски!\n"
        f"{title}\n\n"
        f"+{diff} очков\n"
        f"Текущая серия: 🔥 {streak} дней\n"
        f"Всего очков: {total_points}"
    )
    await callback.answer("Красотка! 🔥")

    # 5) Уведомляем тебя
    try:
        await bot.send_message(
            OWNER_ID,
            f"Твоя девушка выполнила и закрыла задание #{task_id}:\n"
            f"{title}\n\n"
            f"+{diff} очков. Общие очки: {total_points}, 🔥 серия: {streak} дней."
        )
    except Exception:
        pass


# ---------- СТАТИСТИКА ----------

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    # статистика имеет смысл только для девушки, но ты тоже можешь смотреть
    stats = get_or_create_stats(GIRL_ID)
    _, points, completed, streak, last_date = stats

    text = (
        "Статистика девушки:\n\n"
        f"Очки: <b>{points}</b>\n"
        f"Выполнено задач: <b>{completed}</b>\n"
        f"🔥 Серия: <b>{streak}</b> дней\n"
    )
    if last_date:
        text += f"Последний день выполнения: <code>{last_date}</code>"
    await message.answer(text)


# ---------- НАПОМИНАНИЕ ----------

@dp.message(Command("remind"))
async def cmd_remind(message: Message, bot: Bot):
    if message.from_user.id != OWNER_ID:
        return

    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer("Использование: /remind <id_задачи>")
        return

    try:
        task_id = int(parts[1])
    except ValueError:
        await message.answer("ID задачи должен быть числом.")
        return

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT title, difficulty FROM tasks WHERE id = ? AND active = 1", (task_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        await message.answer("Такой активной задачи не найдено.")
        return

    title, diff = row

    # отправляем девушке напоминание
    await bot.send_message(
        GIRL_ID,
        f"🔔 Напоминание от твоего мужчины:\n\n"
        f"Задание #{task_id}: {title}\n"
        f"Сложность: {difficulty_to_label(diff)}"
    )

    await message.answer("Напоминание отправлено ✅")


async def main():
    init_db()
    bot = Bot(BOT_TOKEN, parse_mode="HTML")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
