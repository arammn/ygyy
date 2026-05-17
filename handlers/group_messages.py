"""Group message handlers – with robust /ignore, /unignore, /ignoredlist."""
from telegram import Update
from telegram.ext import MessageHandler, filters, ContextTypes, CommandHandler
from database import Database
from auction import AuctionManager
from lucky_draw import LuckyDrawManager
from dice_game import DiceGameManager
from guess_number import GuessNumberManager
from .admin_private import status_public
import logging

logger = logging.getLogger(__name__)

db = Database()
auction_mgr = AuctionManager()
lucky_mgr = LuckyDrawManager()
dice_mgr = DiceGameManager()
guess_mgr = GuessNumberManager()

async def group_msg_handler(update: Update, context):
    chat = update.effective_chat
    if chat.type in ["group", "supergroup"]:
        await db.upsert_group(chat.id, chat.title or f"Group {chat.id}", chat.type)

    msg = update.effective_message
    if not msg: return
    # Skip service messages
    if msg.new_chat_members or msg.left_chat_member or msg.group_chat_created or msg.migrate_to_chat_id:
        return

    if msg.entities:
        for e in msg.entities:
            if e.type == "bot_command":
                return

    if not await db.any_game_active():
        if hash(msg.message_id) % 10 == 0:
            logger.debug(f"[GROUP] idle msg from {update.effective_user.id}")
        return

    logger.info(f"[GROUP] msg from {update.effective_user.id} in {chat.id}, paid_stars={getattr(msg,'paid_star_count',0)}")
    await auction_mgr.process_bid(update, context)
    await lucky_mgr.process_message(update, context)
    await dice_mgr.process_message(update, context)
    await guess_mgr.process_message(update, context)

# ── Helper to get target user ID from command ──
async def get_target_user_id(update: Update, context) -> int:
    """Extract user ID from reply, mention, or argument. Returns None if not found."""
    msg = update.message
    # 1) Reply to a user
    if msg.reply_to_message and msg.reply_to_message.from_user:
        return msg.reply_to_message.from_user.id

    # 2) Text mention entity
    if msg.entities:
        for entity in msg.entities:
            if entity.type in ("text_mention", "mention"):
                if entity.user:
                    return entity.user.id
                # For plain mention (@username), we need to resolve
                if entity.type == "mention":
                    username = msg.text[entity.offset:entity.offset+entity.length].strip('@')
                    try:
                        chat_member = await context.bot.get_chat(update.effective_chat.id)
                        # Can't easily get user by username in group; try to find by message text
                        # Since bot can't resolve @username directly, we'll require user_id or reply
                    except:
                        pass

    # 3) First argument is numeric user_id
    if context.args:
        try:
            return int(context.args[0])
        except ValueError:
            pass
    return None

# ── Ignore commands (chat admins only) ──
async def ignore_cmd(update: Update, context):
    chat_id = update.effective_chat.id
    user = update.effective_user
    # Check if user is chat admin
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        if member.status not in ('administrator', 'creator'):
            await update.message.reply_text("⛔ Только администраторы могут использовать эту команду.")
            return
    except:
        return

    target_id = await get_target_user_id(update, context)
    if not target_id:
        await update.message.reply_text("❌ Ответьте на сообщение пользователя, укажите @username или числовой ID.")
        return
    await db.add_ignored_user(chat_id, target_id)
    await update.message.reply_text(f"🚫 Пользователь <code>{target_id}</code> добавлен в игнорируемые.", parse_mode="HTML")

async def unignore_cmd(update: Update, context):
    chat_id = update.effective_chat.id
    user = update.effective_user
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        if member.status not in ('administrator', 'creator'): return
    except: return

    target_id = await get_target_user_id(update, context)
    if not target_id:
        await update.message.reply_text("❌ Ответьте на сообщение пользователя, укажите @username или числовой ID.")
        return
    await db.remove_ignored_user(chat_id, target_id)
    await update.message.reply_text(f"✅ Пользователь <code>{target_id}</code> удалён из игнорируемых.", parse_mode="HTML")

async def ignoredlist_cmd(update: Update, context):
    chat_id = update.effective_chat.id
    ids = await db.get_ignored_list(chat_id)
    if not ids:
        await update.message.reply_text("📭 Список игнорируемых пуст.")
    else:
        await update.message.reply_text("🚫 Игнорируемые:\n" + "\n".join(f"<code>{uid}</code>" for uid in ids), parse_mode="HTML")

async def grp_status(update: Update, context):
    chat = update.effective_chat
    if update.my_chat_member.new_chat_member.status in ["member", "administrator"]:
        logger.info(f"Added to {chat.title} ({chat.id})")
        await db.upsert_group(chat.id, chat.title or f"Group {chat.id}", chat.type)
        try: await context.bot.send_message(chat.id, "👋 Бот активирован! Используйте /start в личке для управления ивентами.")
        except: pass

def register_group_handlers(app):
    app.add_handler(MessageHandler(filters.ChatType.GROUPS, group_msg_handler))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, grp_status))
    app.add_handler(CommandHandler("status", status_public))
    app.add_handler(CommandHandler("ignore", ignore_cmd))
    app.add_handler(CommandHandler("unignore", unignore_cmd))
    app.add_handler(CommandHandler("ignoredlist", ignoredlist_cmd))
