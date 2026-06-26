"""
auction.py — Система аукциона.

Правила:
  • До первой ставки таймер НЕ идёт.
  • После первой ставки запускается обратный отсчёт (duration секунд).
  • Каждая новая ставка от ДРУГОГО пользователя сбрасывает таймер заново.
  • Одна и та же ставка от лидера НЕ сбрасывает таймер.
  • Последний написавший до окончания таймера побеждает.

Команды (только администраторам, в группе):
  /startauction [секунды] [описание приза...]
  /stopauction

Финальное сообщение о победителе отправляется в группу и настраивается
через шаблон AUCTION_WIN в меню администратора.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_IDS, DEFAULT_AUCTION_DURATION
from ignore_system import IgnoreSystem
from logger import BotLogger
from message_manager import message_manager

log = logging.getLogger(__name__)


@dataclass
class AuctionState:
    chat_id: int
    duration: int
    prize: str
    # end_time is set when the first bid arrives; None means "waiting for first bid"
    end_time: Optional[float] = None
    current_leader: Optional[str] = None
    current_leader_id: Optional[int] = None
    last_message_id: Optional[int] = None
    countdown_task: Optional[asyncio.Task] = None
    finished: bool = False
    bid_count: int = 0
    # Generation counter to cancel stale countdown tasks after a bid reset
    generation: int = 0

    @property
    def remaining(self) -> float:
        if self.end_time is None:
            return float(self.duration)
        return max(0.0, self.end_time - time.monotonic())

    @property
    def started(self) -> bool:
        """True once the first bid has arrived and countdown is running."""
        return self.end_time is not None


class AuctionEvent:
    def __init__(self, bot_logger: BotLogger, ignore_system: IgnoreSystem) -> None:
        self._logger = bot_logger
        self._ignore = ignore_system
        self._states: dict[int, AuctionState] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    # ── Доступ к состоянию ────────────────────────────────────────────────

    def is_active(self, chat_id: int) -> bool:
        return chat_id in self._states and not self._states[chat_id].finished

    def active_chats(self) -> list[int]:
        return [cid for cid, s in self._states.items() if not s.finished]

    def get_state(self, chat_id: int) -> Optional[AuctionState]:
        return self._states.get(chat_id)

    def _lock(self, chat_id: int) -> asyncio.Lock:
        if chat_id not in self._locks:
            self._locks[chat_id] = asyncio.Lock()
        return self._locks[chat_id]

    # ── Обработчики команд ────────────────────────────────────────────────

    async def cmd_start_auction(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not user or user.id not in ADMIN_IDS:
            return

        if self.is_active(update.effective_chat.id):
            await update.message.reply_text("⚠️ В этой группе уже идёт аукцион!")
            return

        args = context.args or []
        duration = DEFAULT_AUCTION_DURATION
        prize = "Сюрприз"
        if args:
            if args[0].isdigit():
                duration = int(args[0])
                prize = " ".join(args[1:]) if len(args) > 1 else prize
            else:
                prize = " ".join(args)

        await self._start(update, context, duration, prize)

    async def cmd_stop_auction(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not user or user.id not in ADMIN_IDS:
            return
        chat_id = update.effective_chat.id
        if not self.is_active(chat_id):
            await update.message.reply_text("Аукцион не запущен.")
            return
        await self._end_auction(context.bot, chat_id, forced=True)
        await update.message.reply_text("🛑 Аукцион остановлен администратором.")

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query:
            await query.answer()

    # ── Вспомогательные методы для админ-панели ───────────────────────────

    async def edit_prize(self, chat_id: int, new_prize: str) -> bool:
        state = self._states.get(chat_id)
        if not state or state.finished:
            return False
        state.prize = new_prize
        return True

    async def edit_duration(self, chat_id: int, extra_seconds: int) -> bool:
        """Продлевает аукцион на extra_seconds секунд (быстрое продление)."""
        state = self._states.get(chat_id)
        if not state or state.finished:
            return False
        if state.end_time is not None:
            state.end_time += extra_seconds
        else:
            state.duration += extra_seconds
        return True

    async def set_duration(self, chat_id: int, new_duration: int, bot) -> bool:
        """
        Устанавливает новую базовую длительность аукциона.
        Отправляет уведомление в группу.
        """
        state = self._states.get(chat_id)
        if not state or state.finished:
            return False
        state.duration = new_duration
        # Если аукцион уже идёт, сообщим, что новые ставки будут использовать это значение.
        # При желании можно сразу скорректировать текущий end_time (как в edit_duration),
        # но по условию «после следующей ставки время будет обновлённым» оставим без изменения.
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    f"⚙️ <b>Длительность аукциона изменена на {new_duration} секунд.</b>\n"
                    f"Новое время вступит в силу после следующей ставки."
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            log.warning("Не удалось отправить уведомление об изменении длительности: %s", e)
        return True

    async def force_stop(self, chat_id: int, bot) -> bool:
        if not self.is_active(chat_id):
            return False
        await self._end_auction(bot, chat_id, forced=True)
        return True

    # ── Основная логика ───────────────────────────────────────────────────

    async def _start(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                     duration: int, prize: str) -> None:
        chat_id = update.effective_chat.id

        state = AuctionState(chat_id=chat_id, duration=duration, prize=prize, end_time=None)
        state.generation = 0
        self._states[chat_id] = state

        text = message_manager.render("AUCTION_START", prize=prize, duration=duration)
        msg = await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        state.last_message_id = msg.message_id

        await self._logger.log_event(
            "АУКЦИОН", f"Запущен в чате {chat_id} | Приз: {prize} | Длительность: {duration}с"
        )

    async def _start_countdown(self, bot, chat_id: int, gen: int) -> None:
        """
        Запускается после первой ставки. Работает, пока поколение совпадает.
        Отправляет предупреждения и завершает аукцион.
        """
        state = self._states.get(chat_id)
        if not state:
            return

        milestones_hit: set[str] = set()

        while True:
            await asyncio.sleep(0.5)
            state = self._states.get(chat_id)
            if not state or state.finished or state.generation != gen:
                return

            remaining = state.remaining
            if remaining <= 0:
                await self._end_auction(bot, chat_id)
                return

            # 10 секунд
            if remaining <= 10 and "10s" not in milestones_hit:
                milestones_hit.add("10s")
                await self._send_countdown_alert(bot, state, "10 секунд")
            else:
                for sec in (5, 4, 3, 2, 1):
                    key = f"{sec}s"
                    if remaining <= sec and key not in milestones_hit:
                        milestones_hit.add(key)
                        label = f"{sec} секунды" if sec >= 2 else "1 секунда"
                        await self._send_countdown_alert(bot, state, label)
                        break

    def _reset_milestones(self, task: Optional[asyncio.Task]) -> None:
        if task and not task.done():
            task.cancel()

    async def _send_countdown_alert(self, bot, state: AuctionState, label: str) -> None:
        leader = f"@{state.current_leader}" if state.current_leader else "Никто пока!"
        text = message_manager.render("AUCTION_COUNTDOWN", label=label, leader=leader)
        try:
            await bot.send_message(chat_id=state.chat_id, text=text, parse_mode="HTML")
        except Exception as e:
            log.warning("Ошибка отправки уведомления обратного отсчёта: %s", e)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        state = self._states.get(chat_id)
        if not state or state.finished:
            return

        user = update.effective_user
        if not user:
            return
        if self._ignore.should_skip(update):
            return
        if await _is_group_admin(update, context):
            return

        username = user.username or user.first_name

        async with self._lock(chat_id):
            # ── Тот же человек не перебивает ────────────────────────────
            if state.current_leader_id == user.id:
                remaining = int(state.remaining)
                text = message_manager.render(
                    "AUCTION_SAME_BID",
                    username=username,
                    bid_count=state.bid_count,
                    remaining=remaining,
                )
                try:
                    await update.message.reply_text(text, parse_mode="HTML")
                except Exception as e:
                    log.warning("Ошибка ответа на повторную ставку: %s", e)
                return

            # ── Новый лидер ────────────────────────────────────────────
            state.current_leader = username
            state.current_leader_id = user.id
            state.bid_count += 1
            state.generation += 1  # все старые задачи обратного отсчёта перестанут работать

            if not state.started:
                # Первая ставка – запускаем таймер
                state.end_time = time.monotonic() + state.duration
                state.countdown_task = asyncio.create_task(
                    self._start_countdown(context.bot, chat_id, state.generation)
                )
                remaining = int(state.remaining)
                text = message_manager.render(
                    "AUCTION_FIRST_BID", username=username, remaining=remaining
                )
            else:
                # Сброс таймера
                self._reset_milestones(state.countdown_task)
                state.end_time = time.monotonic() + state.duration
                state.countdown_task = asyncio.create_task(
                    self._start_countdown(context.bot, chat_id, state.generation)
                )
                remaining = int(state.remaining)
                text = message_manager.render(
                    "AUCTION_NEW_BID", username=username, remaining=remaining
                )

        try:
            await update.message.reply_text(text, parse_mode="HTML")
        except Exception as e:
            log.warning("Ошибка ответа на ставку: %s", e)

    async def _end_auction(self, bot, chat_id: int, forced: bool = False) -> None:
        async with self._lock(chat_id):
            state = self._states.get(chat_id)
            if not state or state.finished:
                return
            state.finished = True
            current_task = asyncio.current_task()
            if (
                state.countdown_task
                and not state.countdown_task.done()
                and state.countdown_task != current_task
            ):
                state.countdown_task.cancel()

        if forced:
            text = message_manager.render("AUCTION_STOPPED")
        elif not state.current_leader:
            text = message_manager.render("AUCTION_NO_WINNER")
        else:
            text = message_manager.render(
                "AUCTION_WIN",
                winner=state.current_leader,
                prize=state.prize,
                bid_count=state.bid_count,
            )
            await self._logger.log_winner("АУКЦИОН", state.current_leader, state.prize)

        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        except Exception as e:
            log.error("Не удалось отправить финальное сообщение аукциона: %s", e)

        self._states.pop(chat_id, None)


async def _is_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False