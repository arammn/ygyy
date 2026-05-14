"""Auction core – Russian, HTML, race‑free, optimized."""
import time, asyncio, logging, html
from database import Database

logger = logging.getLogger(__name__)
COUNTDOWN_SECS = [30, 15, 10, 5, 4, 3, 2, 1]

class AuctionManager:
    def __init__(self):
        self.db = Database()
        self.locks = {}

    def _lock(self, chat_id):
        if chat_id not in self.locks:
            self.locks[chat_id] = asyncio.Lock()
        return self.locks[chat_id]

    async def process_bid(self, update, context):
        msg = update.effective_message
        chat_id = update.effective_chat.id
        user = update.effective_user

        game = await self.db.get_active_game(chat_id)
        if not game or user.is_bot:
            return
        if await self._is_admin(chat_id, user.id, context):
            return

        lock = self._lock(chat_id)
        async with lock:
            game = await self.db.get_active_game(chat_id)
            if not game or game.get('current_leader_id') == user.id:
                return

            paid_stars = getattr(msg, 'paid_star_count', 0)
            if user.username:
                user_disp = f"@{user.username}"
            else:
                user_disp = html.escape(user.full_name)

            duration = game['timer_duration']
            mins = duration // 60
            secs = duration % 60
            time_left = f"{mins} мин" if secs == 0 else f"{mins} мин {secs} сек"

            await msg.reply_text(
                f"🔄 <b>Перебито!</b>\n"
                f"Новый лидер: <b>{user_disp}</b>. До конца: {time_left}.",
                parse_mode="HTML"
            )
            await self.db.increment_bid(chat_id, paid_stars)
            await self._reset_timer(context, chat_id, user.id, user_disp, game)

    async def _reset_timer(self, context, chat_id, user_id, user_name, game):
        if game.get('job_name'):
            for j in context.job_queue.jobs():
                if j.name == game['job_name']:
                    j.schedule_removal()
                    break
        prefix = f"countdown_{chat_id}_"
        for j in context.job_queue.jobs():
            if j.name and j.name.startswith(prefix):
                j.schedule_removal()

        job_name = f"auction_{chat_id}_{int(time.time())}"
        context.job_queue.run_once(
            self._end_auction, game['timer_duration'],
            chat_id=chat_id, name=job_name,
            data={'chat_id': chat_id, 'job_name': job_name}
        )
        for sec in COUNTDOWN_SECS:
            if game['timer_duration'] > sec:
                delay = game['timer_duration'] - sec
                context.job_queue.run_once(
                    self._send_countdown, delay,
                    chat_id=chat_id, name=f"{prefix}{sec}",
                    data={'chat_id': chat_id, 'seconds_left': sec}
                )
        await self.db.update_leader(chat_id, user_id, user_name, time.time(), job_name)

    async def _send_countdown(self, context):
        data = context.job.data
        chat_id = data['chat_id']
        sec = data['seconds_left']
        game = await self.db.get_active_game(chat_id)
        if not game:
            return
        leader = game.get('leader_name', 'Никто')
        await context.bot.send_message(
            chat_id,
            f"⚠️ ОСТАЛОСЬ {sec} СЕК.\nИ <b>{leader}</b> ЗАБЕРЕТ ПРИЗ!!!!",
            parse_mode="HTML"
        )

    async def _end_auction(self, context):
        data = context.job.data
        chat_id = data['chat_id']
        job_name = data.get('job_name', '')
        lock = self._lock(chat_id)
        async with lock:
            prefix = f"countdown_{chat_id}_"
            for j in context.job_queue.jobs():
                if j.name and j.name.startswith(prefix):
                    j.schedule_removal()
            game = await self.db.get_active_game(chat_id)
            if not game or (job_name and game.get('job_name') != job_name):
                return
            winner_name = game.get('leader_name', 'Никто')
            prize = html.escape(game.get('description', '🎁'))
            if winner_name:
                await context.bot.send_message(
                    chat_id,
                    f"🎉 <b>Ивент завершён!</b>\n\n"
                    f"<b>{winner_name}</b> получает подарок: {prize}!",
                    parse_mode="HTML"
                )
                try:
                    await context.bot.send_message(
                        game['current_leader_id'],
                        f"Поздравляем! Вы выиграли: {prize}"
                    )
                except: pass
            else:
                await context.bot.send_message(chat_id, "⏰ Ивент завершён без ставок.")
            await self.db.deactivate_game(chat_id)
        self.locks.pop(chat_id, None)

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

    async def restore_timers(self, app):
        games = await self.db.get_all_active_games()
        now = time.time()
        for g in games:
            chat_id = g['chat_id']
            if not g.get('timer_start'):
                logger.info(f"Auction in {chat_id} active but no bids, nothing to restore.")
                continue

            elapsed = now - g['timer_start']
            remaining = g['timer_duration'] - elapsed

            if remaining > 0:
                leader = g.get('leader_name', 'Никто')
                mins = int(remaining) // 60
                secs = int(remaining) % 60
                time_str = f"{mins} мин" if secs == 0 else f"{mins} мин {secs} сек"
                if leader:
                    try:
                        await app.bot.send_message(
                            chat_id,
                            f"🔄 Бот был перезапущен.\n"
                            f"Текущий лидер: <b>{leader}</b>\n"
                            f"Осталось: {time_str}.",
                            parse_mode="HTML"
                        )
                    except: pass

                job_name = f"auction_{chat_id}_{int(now)}"
                app.job_queue.run_once(
                    self._end_auction, remaining,
                    chat_id=chat_id, name=job_name,
                    data={'chat_id': chat_id, 'job_name': job_name}
                )
                prefix = f"countdown_{chat_id}_"
                for sec in COUNTDOWN_SECS:
                    if remaining > sec:
                        delay = remaining - sec
                        app.job_queue.run_once(
                            self._send_countdown, delay,
                            chat_id=chat_id, name=f"{prefix}{sec}",
                            data={'chat_id': chat_id, 'seconds_left': sec}
                        )
                await self.db.update_leader(chat_id, g['current_leader_id'], leader, g['timer_start'], job_name)
            else:
                winner_name = g.get('leader_name', 'Никто')
                try:
                    await app.bot.send_message(
                        chat_id,
                        f"🏆 Ивент завершился, пока бот был офлайн. Победитель: {winner_name}"
                    )
                except: pass
                await self.db.deactivate_game(chat_id)