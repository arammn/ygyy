"""Dice Game – reacts to Telegram dice."""
import logging, html
from config import Config
from database import Database

logger = logging.getLogger(__name__)

class DiceGameManager:
    def __init__(self): self.db = Database()

    async def process_message(self, update, context):
        msg = update.effective_message
        if not msg or not msg.dice: return
        chat_id = update.effective_chat.id
        user = update.effective_user

        game = await self.db.get_active_dice_game(chat_id)
        if not game or user.is_bot: return
        if await self.db.is_ignored(chat_id, user.id): return
        if msg.dice.emoji != game['dice_emoji']: return
        if msg.dice.value != game['winning_value']: return

        prize = html.escape(game['prize'])
        if user.username: winner = f"@{user.username}"
        else: winner = html.escape(user.full_name)
        win_msg = await msg.reply_text(f"🎲 <b>Победа в игре!</b>\n<b>{winner}</b> выбил {game['winning_value']} и выиграл: {prize}!", parse_mode="HTML")
        try: await context.bot.pin_chat_message(chat_id, win_msg.message_id, disable_notification=False)
        except: pass
        for admin_id in Config.ADMIN_IDS:
            dm_text = f"🎲 <b>Dice Win!</b>\nГруппа: <code>{chat_id}</code>\nПобедитель: <b>{winner}</b>\nПриз: {prize}\nID: <code>{user.id}</code>\nЭмодзи: {msg.dice.emoji}, значение: {msg.dice.value}"
            if user.username: dm_text += f"\nЮзернейм: @{user.username}"
            try: await context.bot.send_message(admin_id, dm_text, parse_mode="HTML")
            except: pass
