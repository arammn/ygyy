"""Group message handlers."""
from telegram import Update
from telegram.ext import MessageHandler, filters, ContextTypes, CommandHandler
from database import Database
from auction import AuctionManager
from lucky_draw import LuckyDrawManager
from dice_game import DiceGameManager
from .admin_private import status_public
import logging

logger = logging.getLogger(__name__)
db = Database()
auction_mgr = AuctionManager()
lucky_mgr = LuckyDrawManager()
dice_mgr = DiceGameManager()

async def group_msg_handler(update: Update, context):
    chat = update.effective_chat
    if chat.type in ["group", "supergroup"]:
        await db.upsert_group(chat.id, chat.title or f"Group {chat.id}", chat.type)

    msg = update.effective_message
    if not msg:
        return
    if msg.entities:
        for e in msg.entities:
            if e.type == "bot_command":
                logger.info(f"[GROUP] command ignored from {update.effective_user.id}")
                return

    logger.info(f"[GROUP] msg from {update.effective_user.id} in {chat.id}, paid_stars={getattr(msg, 'paid_star_count', 0)}")
    await auction_mgr.process_bid(update, context)
    await lucky_mgr.process_message(update, context)
    await dice_mgr.process_message(update, context)

async def grp_status(update: Update, context):
    chat = update.effective_chat
    if update.my_chat_member.new_chat_member.status in ["member", "administrator"]:
        logger.info(f"Added to {chat.title} ({chat.id})")
        await db.upsert_group(chat.id, chat.title or f"Group {chat.id}", chat.type)
        try:
            await context.bot.send_message(chat.id, "👋 Бот активирован! Используйте /start в личке для управления ивентами.")
        except: pass

def register_group_handlers(app):
    app.add_handler(MessageHandler(filters.ChatType.GROUPS, group_msg_handler))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, grp_status))
    app.add_handler(CommandHandler("status", status_public))