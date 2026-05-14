"""Lucky Draw mini-game – pin win, notify admins."""
import random, logging, time, html
from config import Config
from database import Database

logger = logging.getLogger(__name__)

class LuckyDrawManager:
    def __init__(self):
        self.db = Database()

    async def process_message(self, update, context):
        chat_id = update.effective_chat.id
        user = update.effective_user
        msg = update.effective_message

        draw = await self.db.get_active_lucky_draw(chat_id)
        if not draw or user.is_bot:
            return
        if await self._is_admin(chat_id, user.id, context):
            return

        chance = draw['chance']
        roll = random.randint(1, 100)
        if roll <= chance:
            prize = html.escape(draw['prize'])
            if user.username:
                winner = f"@{user.username}"
            else:
                winner = html.escape(user.full_name)
            win_msg = await msg.reply_text(
                f"🎉 Поздравляем! <b>{winner}</b> выиграл: {prize}!",
                parse_mode="HTML"
            )
            try:
                await context.bot.pin_chat_message(chat_id, win_msg.message_id, disable_notification=False)
            except Exception as e:
                logger.error(f"Could not pin message: {e}")

            for admin_id in Config.ADMIN_IDS:
                dm_text = (
                    f"🎰 <b>Lucky Draw Win!</b>\n"
                    f"Группа: <code>{chat_id}</code>\n"
                    f"Победитель: <b>{winner}</b>\n"
                    f"Приз: {prize}\n"
                    f"ID: <code>{user.id}</code>"
                )
                if user.username:
                    dm_text += f"\nЮзернейм: @{user.username}"
                try:
                    await context.bot.send_message(admin_id, dm_text, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Failed to notify admin {admin_id}: {e}")

    async def _is_admin(self, chat_id, user_id, context):
        cache = context.bot_data.setdefault('admin_cache', {})
        key = (chat_id, user_id)
        now = time.time()
        if key in cache and (now - cache[key]['time'] < 60):
            return cache[key]['is_admin']
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            is_admin = member.status in ('administrator', 'creator')
            cache[key] = {'time': now, 'is_admin': is_admin}
            return is_admin
        except:
            return False