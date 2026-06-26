"""
bot.py — Точка входа Telegram Event Bot.
"""

import asyncio
import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

from config import BOT_TOKEN
from admin_panel import AdminPanel
from ignore_system import IgnoreSystem
from auction import AuctionEvent
from casino import CasinoEvent
from random_event import RandomEvent
from logger import BotLogger

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    bot_logger = application.bot_data["logger"]
    bot_logger.attach_bot(application.bot)
    await bot_logger.log("🤖 Бот успешно запущен!")


def main() -> None:
    bot_logger    = BotLogger()
    ignore_system = IgnoreSystem()
    admin_panel   = AdminPanel(bot_logger, ignore_system)
    auction       = AuctionEvent(bot_logger, ignore_system)
    casino        = CasinoEvent(bot_logger, ignore_system)
    random_event  = RandomEvent(bot_logger, ignore_system)

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .post_init(post_init)
        .build()
    )

    application.bot_data["logger"]        = bot_logger
    application.bot_data["ignore_system"] = ignore_system
    application.bot_data["admin_panel"]   = admin_panel
    application.bot_data["auction"]       = auction
    application.bot_data["casino"]        = casino
    application.bot_data["random_event"]  = random_event

    # ── Команды администратора ──────────────────────────────────────────────
    application.add_handler(CommandHandler("start",        admin_panel.cmd_start))
    application.add_handler(CommandHandler("menu",         admin_panel.cmd_menu))
    application.add_handler(CommandHandler("logs",         admin_panel.cmd_logs))
    application.add_handler(CommandHandler("setemoji",     admin_panel.cmd_setemoji))
    application.add_handler(CommandHandler("setmessage",   admin_panel.cmd_setmessage))
    application.add_handler(CommandHandler("resetmessage", admin_panel.cmd_resetmessage))

    # ── Команды системы игнора ──────────────────────────────────────────────
    application.add_handler(CommandHandler("ignore",     ignore_system.cmd_ignore))
    application.add_handler(CommandHandler("unignore",   ignore_system.cmd_unignore))
    application.add_handler(CommandHandler("ignorelist", ignore_system.cmd_ignorelist))

    # ── Команды событий ─────────────────────────────────────────────────────
    application.add_handler(CommandHandler("startauction", auction.cmd_start_auction))
    application.add_handler(CommandHandler("stopauction",  auction.cmd_stop_auction))
    application.add_handler(CommandHandler("startcasino",  casino.cmd_start_casino))
    application.add_handler(CommandHandler("stopcasino",   casino.cmd_stop_casino))
    application.add_handler(CommandHandler("startevent",   random_event.cmd_start_event))
    application.add_handler(CommandHandler("stopevent",    random_event.cmd_stop_event))

    # ── Обработчики inline-кнопок ───────────────────────────────────────────
    application.add_handler(CallbackQueryHandler(admin_panel.handle_callback))

    # ── Обработчик текста в личном чате (для потоков редактирования) ────────
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND,
            admin_panel.handle_text,
        )
    )

    # ── Обработчик обычных сообщений в группе (аукцион + розыгрыш) ─────────
    application.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & ~filters.COMMAND & ~filters.Dice.ALL,
            handle_group_message,
        )
    )

    # ── Обработчик dice/слот-машины в группе (казино) ───────────────────────
    # Casino ONLY reacts to 🎰 slot machine dice messages.
    # This separate handler ensures dice messages are caught even though
    # the default group handler excludes them with ~filters.Dice.ALL.
    application.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.Dice.ALL,
            handle_group_dice,
        )
    )

    logger.info("Запуск бота...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles regular (non-dice) group messages for auction and random event."""
    auction      = context.bot_data["auction"]
    random_event = context.bot_data["random_event"]
    chat_id = update.effective_chat.id

    tasks = []
    if auction.is_active(chat_id):
        tasks.append(auction.handle_message(update, context))
    if random_event.is_active(chat_id):
        tasks.append(random_event.handle_message(update, context))

    if tasks:
        await asyncio.gather(*tasks)


async def handle_group_dice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles dice/slot machine messages in groups.
    Only the casino reacts to 🎰 slot machine messages.
    Regular auction and random event also receive them so participants
    can "bid" or "attempt" with any message type.
    """
    casino       = context.bot_data["casino"]
    auction      = context.bot_data["auction"]
    random_event = context.bot_data["random_event"]
    chat_id = update.effective_chat.id

    tasks = []

    # Casino gets ALL dice messages; internally it filters for 🎰 only
    if casino.is_active(chat_id):
        tasks.append(casino.handle_message(update, context))

    # Auction and random event also count dice messages as bids/attempts
    if auction.is_active(chat_id):
        tasks.append(auction.handle_message(update, context))
    if random_event.is_active(chat_id):
        tasks.append(random_event.handle_message(update, context))

    if tasks:
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    main()
