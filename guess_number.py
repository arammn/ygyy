"""Guess the Number mini‑game."""
import random, logging, html, time
from config import Config
from database import Database

logger = logging.getLogger(__name__)

class GuessNumberManager:
    def __init__(self): self.db = Database()

    async def process_message(self, update, context):
        msg = update.effective_message
        if not msg.text: return
        chat_id = update.effective_chat.id
        user = update.effective_user

        game = await self.db.get_active_guess_number(chat_id)
        if not game or user.is_bot: return
        if await self.db.is_ignored(chat_id, user.id): return

        try: guess = int(msg.text.strip())
        except: return

        if guess < game['min_num'] or guess > game['max_num']: return
        if guess != game['secret_number']: return

        prize = html.escape(game['prize'])
        if user.username: winner = f"@{user.username}"
        else: winner = html.escape(user.full_name)

        win_msg = await msg.reply_text(
            f"🎯 <b>Число угадано!</b>\n<b>{winner}</b> угадал число <b>{game['secret_number']}</b> и выиграл: {prize}!",
            parse_mode="HTML"
        )
        try: await context.bot.pin_chat_message(chat_id, win_msg.message_id, disable_notification=False)
        except: pass

        for admin_id in Config.ADMIN_IDS:
            dm_text = f"🎯 <b>Guess Win!</b>\nГруппа: <code>{chat_id}</code>\nПобедитель: <b>{winner}</b>\nПриз: {prize}\nID: <code>{user.id}</code>"
            if user.username: dm_text += f"\nЮзернейм: @{user.username}"
            try: await context.bot.send_message(admin_id, dm_text, parse_mode="HTML")
            except: pass

        await self._end_guess_game(context, chat_id)

    async def _end_guess_game(self, context, chat_id):
        game = await self.db.get_active_guess_number(chat_id)
        if not game: return
        if game.get('job_name'):
            for j in context.job_queue.jobs():
                if j.name == game['job_name']: j.schedule_removal()
        await self.db.deactivate_guess_number(chat_id)

    async def restore_timers(self, app):
        games = await self.db.get_all_active_guess_numbers()
        now = time.time()
        for g in games:
            if g.get('timer_start') and g['duration_minutes']>0:
                elapsed = now - g['timer_start']
                remaining = g['duration_minutes']*60 - elapsed
                if remaining > 0:
                    job_name = f"guess_end_{g['chat_id']}_{int(now)}"
                    app.job_queue.run_once(
                        lambda ctx, cid=g['chat_id']: self._end_guess_game(ctx, cid),
                        remaining, chat_id=g['chat_id'], name=job_name
                    )
                    await self.db.set_guess_number_timer(g['chat_id'], g['timer_start'], job_name)
                else:
                    await self._end_guess_game(app, g['chat_id'])
                    try: await app.bot.send_message(g['chat_id'], "⏰ Время игры «Угадай число» вышло, победителей нет.")
                    except: pass
