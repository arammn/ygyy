"""
config.py — Центральная конфигурация Telegram Event Bot.
"""

import os
from pathlib import Path

# ── Токен бота ────────────────────────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "8949793948:AAEymt1xE6-Dz3ygj0Evyw_qurF6errFPsM")

# ── ID администраторов ────────────────────────────────────────────────────────
ADMIN_IDS_FILE: Path = Path("admins.txt")

def load_admin_ids() -> set[int]:
    ids: set[int] = set()
    if ADMIN_IDS_FILE.exists():
        for line in ADMIN_IDS_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and line.isdigit():
                ids.add(int(line))
    return ids

ADMIN_IDS: set[int] = load_admin_ids()

# ── Пути к файлам ─────────────────────────────────────────────────────────────
IGNORE_FILE: Path   = Path("ignore_list.txt")
LOG_FILE: Path      = Path("logs.txt")
EMOJI_FILE: Path    = Path("emojis.json")
MESSAGES_FILE: Path = Path("messages.json")

# ── Эмодзи по умолчанию ──────────────────────────────────────────────────────
DEFAULT_EMOJIS: dict[str, str] = {
    "EMOJI_WIN":      "🏆",
    "EMOJI_AUCTION":  "🔨",
    "EMOJI_CASINO":   "🎰",
    "EMOJI_EVENT":    "🎯",
    "EMOJI_ALERT":    "🚨",
    "EMOJI_SETTINGS": "⚙️",
    "EMOJI_LOGS":     "📜",
    "EMOJI_IGNORE":   "🚫",
    "EMOJI_BID":      "💰",
    "EMOJI_PRIZE":    "🎁",
    "EMOJI_TIMER":    "⏱",
    "EMOJI_FIRE":     "🔥",
    "EMOJI_LUCK":     "🍀",
    "EMOJI_WINNER":   "🎉",
    "EMOJI_STAR":     "⭐",
}

# ── Шаблоны сообщений по умолчанию ───────────────────────────────────────────
DEFAULT_MESSAGES: dict[str, str] = {
    # ── Аукцион ──────────────────────────────────────────────────────────
    "AUCTION_START": (
        "{EMOJI_AUCTION} <b>АУКЦИОН НАЧАЛСЯ!</b>\n\n"
        "{EMOJI_PRIZE} Приз: <b>{prize}</b>\n"
        "{EMOJI_TIMER} Длительность: <b>{duration} сек.</b>\n\n"
        "Каждое сообщение — ставка! Последний написавший побеждает!\n"
        "<i>Напишите сейчас, чтобы выйти вперёд!</i>"
    ),
    "AUCTION_FIRST_BID": (
        "{EMOJI_FIRE} <b>Первая ставка от @{username}!</b>\n"
        "{EMOJI_WIN} Лидирует!\n"
        "{EMOJI_TIMER} Осталось {remaining} сек."
    ),
    "AUCTION_SAME_BID": (
        "{EMOJI_FIRE} @{username} укрепляет лидерство! (ставка #{bid_count})\n"
        "{EMOJI_TIMER} Осталось {remaining} сек."
    ),
    "AUCTION_NEW_BID": (
        "{EMOJI_FIRE} <b>Новая ставка от @{username}!</b>\n"
        "{EMOJI_WIN} <b>Новый лидер: @{username}</b>\n"
        "{EMOJI_TIMER} Осталось {remaining} сек."
    ),
    "AUCTION_COUNTDOWN": (
        "{EMOJI_TIMER} <b>Осталось {label}!</b>\n"
        "{EMOJI_FIRE} Текущий лидер: <b>{leader}</b>\n"
        "<i>Ещё есть время сделать ставку!</i>"
    ),
    "AUCTION_WIN": (
        "{EMOJI_WINNER} <b>АУКЦИОН ЗАВЕРШЁН!</b>\n\n"
        "🏆 Победитель: <b>@{winner}</b>\n"
        "{EMOJI_PRIZE} Приз: <b>{prize}</b>\n\n"
        "Всего ставок: {bid_count}\n"
        "Поздравляем! 🎊"
    ),
    "AUCTION_NO_WINNER": (
        "{EMOJI_AUCTION} <b>Аукцион завершён</b>\n\n"
        "Ставок не было."
    ),
    "AUCTION_STOPPED": (
        "{EMOJI_AUCTION} <b>Аукцион завершён</b>\n\n"
        "Остановлен администратором."
    ),
    # ── Казино ───────────────────────────────────────────────────────────
    "CASINO_START": (
        "{EMOJI_CASINO} <b>КАЗИНО ОТКРЫТО!</b>\n\n"
        "{EMOJI_PRIZE} Приз: <b>{prize}</b>\n\n"
        "{EMOJI_ALERT} Отправляйте 🎰 (слот-машину Telegram)!\n"
        "🎰 Первый, кто выбьет <b>777</b>, побеждает!\n\n"
        "<i>Отправьте эмодзи 🎰 из стикеров Telegram!</i>"
    ),
    "CASINO_WIN": (
        "{EMOJI_CASINO} 🎰🎰🎰\n\n"
        "{EMOJI_WINNER} <b>ДЖЕКПОТ! @{username} выбил 777!</b>\n"
        "{EMOJI_PRIZE} Приз: <b>{prize}</b>\n\n"
        "🎊 Поздравляем! Невероятная удача!"
    ),
    "CASINO_NEAR_MISS": (
        "{EMOJI_CASINO} Почти!\n"
        "@{username} — <i>Два одинаковых значения, но не джекпот! Попробуй ещё!</i>"
    ),
    "CASINO_ROLL": (
        "{EMOJI_CASINO} @{username} крутит барабаны...\n"
        "<i>Результат: {slot_display}</i>"
    ),
    # ── Случайное событие ─────────────────────────────────────────────────
    "RANDOM_START": (
        "{EMOJI_LUCK} <b>СЛУЧАЙНЫЙ РОЗЫГРЫШ НАЧАЛСЯ!</b>\n\n"
        "{EMOJI_PRIZE} Приз: <b>{prize}</b>\n"
        "{EMOJI_ALERT} Шанс победы за сообщение: <b>{chance}%</b>\n"
        "{EMOJI_STAR} Победителей: <b>{max_winners}</b>\n\n"
        "<i>Каждое сообщение даёт шанс выиграть — пишите!</i>"
    ),
    "RANDOM_WIN": (
        "{EMOJI_WINNER} <b>ЕСТЬ ПОБЕДИТЕЛЬ!</b>\n\n"
        "{EMOJI_LUCK} @{username} выиграл!\n"
        "{EMOJI_PRIZE} Приз: <b>{prize}</b>\n\n"
        "{EMOJI_STAR} После {attempts} попыток — удача улыбнулась!\n"
        "🎊 Поздравляем!"
    ),
    "RANDOM_ALL_WINNERS": (
        "{EMOJI_WINNER} <b>ВСЕ ПОБЕДИТЕЛИ ОПРЕДЕЛЕНЫ!</b>\n\n"
        "{EMOJI_PRIZE} Приз: <b>{prize}</b>\n\n"
        "{winners_list}\n\n"
        "🎊 Поздравляем всех победителей!"
    ),
}

# ── Настройки событий ─────────────────────────────────────────────────────────
DEFAULT_AUCTION_DURATION: int    = 30
DEFAULT_CASINO_TARGET: str       = "777"
DEFAULT_RANDOM_WIN_CHANCE: float = 0.05

# ── Параллельность ────────────────────────────────────────────────────────────
MAX_CONCURRENT_HANDLERS: int = 20
