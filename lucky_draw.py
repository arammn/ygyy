"""Lucky Draw – float chance, multi‑winner, timer, gift, ignore."""
import random, logging, time, html, json
from config import Config
from database import Database

logger = logging.getLogger(__name__)

class LuckyDrawManager:
    def __init__(self):
        self.db = Database()

    async def process_message(self, update, context):
        msg = update.effective_message
        chat_id = update.effective_chat.id
        user = update.effective_user

        draw = await self.db.get_active_lucky_draw(chat_id)
        if not draw or user.is_bot:
            return
        if await self.db.is_ignored(chat_id, user.id):
            return
        if await self._is_admin(chat_id, user.id, context):
            return

        chance = draw['chance']
        roll = random.uniform(0, 100)
        if roll > chance:
            return

        prize = html.escape(draw['prize'])
        if user.username:
            winner = f"@{user.username}"
        else:
            winner = html.escape(user.full_name)

        remaining, is_new = await self.db.update_lucky_draw_winner(chat_id, user.id)
        if not is_new:
            return

        gift_id = draw.get('gift_id')
        if gift_id:
            try:
                await self._send_gift(context, user.id, gift_id, prize)
                gift_msg = " 🎁 Подарок отправлен!"
            except Exception as e:
                logger.error(f"Gift send failed: {e}")
                gift_msg = ""
        else:
            gift_msg = ""

        win_msg = await msg.reply_text(
            f"🎉 Поздравляем! <b>{winner}</b> выиграл: {prize}!{gift_msg}",
            parse_mode="HTML"
        )
        try: await context.bot.pin_chat_message(chat_id, win_msg.message_id, disable_notification=False)
        except: pass

        for admin_id in Config.ADMIN_IDS:
            dm_text = f"🎰 <b>Lucky Draw Win!</b>\nГруппа: <code>{chat_id}</code>\nПобедитель: <b>{winner}</b>\nПриз: {prize}\nID: <code>{user.id}</code>"
            if user.username: dm_text += f"\nЮзернейм: @{user.username}"
            try: await context.bot.send_message(admin_id, dm_text, parse_mode="HTML")
            except: pass

        if remaining <= 0:
            await self._end_lucky_draw(context, chat_id, f"Все победители выбраны!")

    async def _send_gift(self, context, user_id, gift_id, prize):
        params = {"user_id": user_id, "gift_id": gift_id, "text": f"Вы выиграли: {prize}", "text_parse_mode": "HTML"}
        result = await context.bot._post("sendGift", params, api_kwargs=None)
        logger.info(f"sendGift result: {result}")

    async def _end_lucky_draw(self, context, chat_id, reason: str = ""):
        game = await self.db.get_active_lucky_draw(chat_id)
        if not game: return
        if game.get('job_name'):
            for j in context.job_queue.jobs():
                if j.name == game['job_name']: j.schedule_removal()
        await self.db.deactivate_lucky_draw(chat_id)
        msg = "🎰 Lucky Draw завершён!"
        if reason: msg += f"\n{reason}"
        try: await context.bot.send_message(chat_id, msg, parse_mode="HTML")
        except: pass

    async def _is_admin(self, chat_id, user_id, context):
        cache = context.bot_data.setdefault('admin_cache', {})
        key = (chat_id, user_id)
        now = time.time()
        if key in cache and (now-cache[key]['time'])<60: return cache[key]['is_admin']
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            is_admin = member.status in ('administrator','creator')
            cache[key] = {'time':now,'is_admin':is_admin}
            return is_admin
        except: return False

    async def restore_timers(self, app):
        draws = await self.db.get_all_active_lucky_draws()
        now = time.time()
        for d in draws:
            if d.get('timer_start') and d['duration_minutes']>0:
                elapsed = now - d['timer_start']
                remaining = d['duration_minutes']*60 - elapsed
                if remaining > 0:
                    job_name = f"lucky_end_{d['chat_id']}_{int(now)}"
                    app.job_queue.run_once(
                        lambda ctx, cid=d['chat_id']: self._end_lucky_draw(ctx, cid, "Время вышло"),
                        remaining, chat_id=d['chat_id'], name=job_name, data={'chat_id': d['chat_id']}
                    )
                    await self.db.set_lucky_draw_timer(d['chat_id'], d['timer_start'], job_name)
                else:
                    await self._end_lucky_draw(app, d['chat_id'], "Время вышло")
