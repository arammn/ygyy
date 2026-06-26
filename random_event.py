"""
random_event.py — Система случайного розыгрыша с поддержкой нескольких победителей.

Каждое сообщение имеет настраиваемую вероятность мгновенной победы.
Можно задать количество победителей — бот продолжает выбирать после первого
победителя до тех пор, пока не будут определены все победители или пока
администратор не остановит розыгрыш.

Команды (только администраторам, в группе):
  /startevent [шанс%] [количество_победителей] [описание приза...]
  Примеры:
    /startevent 5 Сюрприз              — 5%, 1 победитель
    /startevent 5 3 Сюрприз            — 5%, 3 победителя
    /startevent 10 5 500 Stars         — 10%, 5 победителей
  /stopevent
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_IDS, DEFAULT_RANDOM_WIN_CHANCE
from ignore_system import IgnoreSystem
from logger import BotLogger
from message_manager import message_manager

log = logging.getLogger(__name__)


@dataclass
class RandomEventState:
    chat_id: int
    prize: str
    win_chance: float
    max_winners: int = 1          # Total winners to find before auto-stopping
    finished: bool = False
    total_attempts: int = 0
    winners: list[str] = field(default_factory=list)

    @property
    def winners_found(self) -> int:
        return len(self.winners)

    @property
    def all_winners_found(self) -> bool:
        return self.winners_found >= self.max_winners


class RandomEvent:
    def __init__(self, bot_logger: BotLogger, ignore_system: IgnoreSystem) -> None:
        self._logger = bot_logger
        self._ignore = ignore_system
        self._states: dict[int, RandomEventState] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def is_active(self, chat_id: int) -> bool:
        return chat_id in self._states and not self._states[chat_id].finished

    def active_chats(self) -> list[int]:
        return [cid for cid, s in self._states.items() if not s.finished]

    def get_state(self, chat_id: int) -> Optional[RandomEventState]:
        return self._states.get(chat_id)

    def _lock(self, chat_id: int) -> asyncio.Lock:
        if chat_id not in self._locks:
            self._locks[chat_id] = asyncio.Lock()
        return self._locks[chat_id]

    async def cmd_start_event(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not user or user.id not in ADMIN_IDS:
            return
        if self.is_active(update.effective_chat.id):
            await update.message.reply_text("⚠️ Случайный розыгрыш уже запущен!")
            return

        args = context.args or []
        win_chance = DEFAULT_RANDOM_WIN_CHANCE
        max_winners = 1
        prize = "Сюрприз"

        # Parsing: /startevent [chance%] [max_winners] [prize...]
        # chance%      → first arg ending with % or a float/int ≤ 100
        # max_winners  → second arg if it's a plain integer
        # prize        → remaining args joined

        remaining_args = list(args)

        if remaining_args:
            first = remaining_args[0].rstrip("%")
            if first.replace(".", "").isdigit():
                win_chance = max(0.001, min(1.0, float(first) / 100.0))
                remaining_args.pop(0)

        if remaining_args:
            if remaining_args[0].isdigit():
                max_winners = max(1, int(remaining_args[0]))
                remaining_args.pop(0)

        if remaining_args:
            prize = " ".join(remaining_args)

        await self._start(update, context, win_chance, max_winners, prize)

    async def cmd_stop_event(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not user or user.id not in ADMIN_IDS:
            return
        chat_id = update.effective_chat.id
        if not self.is_active(chat_id):
            await update.message.reply_text("Случайный розыгрыш не запущен.")
            return
        state = self._states.pop(chat_id, None)
        if state:
            state.finished = True
            # Send summary of winners so far if any were found
            if state.winners:
                winners_list = "\n".join(
                    f"{i+1}. @{w}" for i, w in enumerate(state.winners)
                )
                await update.message.reply_text(
                    f"🛑 Розыгрыш остановлен.\n\n"
                    f"🏆 Победители ({state.winners_found}/{state.max_winners}):\n{winners_list}",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text("🛑 Случайный розыгрыш остановлен. Победителей не было.")
        else:
            await update.message.reply_text("🛑 Случайный розыгрыш остановлен.")

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

    async def edit_chance(self, chat_id: int, new_chance_pct: float) -> bool:
        state = self._states.get(chat_id)
        if not state or state.finished:
            return False
        state.win_chance = max(0.001, min(1.0, new_chance_pct / 100.0))
        return True

    async def edit_max_winners(self, chat_id: int, new_max: int) -> bool:
        """Change the number of winners mid-event."""
        state = self._states.get(chat_id)
        if not state or state.finished:
            return False
        state.max_winners = max(state.winners_found + 1, new_max)
        return True

    async def force_stop(self, chat_id: int, bot) -> bool:
        if not self.is_active(chat_id):
            return False
        state = self._states.pop(chat_id, None)
        if state:
            state.finished = True
        try:
            await bot.send_message(
                chat_id=chat_id,
                text="🛑 Случайный розыгрыш остановлен администратором."
            )
        except Exception:
            pass
        return True

    # ── Основная логика ───────────────────────────────────────────────────

    async def _start(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                     win_chance: float, max_winners: int, prize: str) -> None:
        chat_id = update.effective_chat.id
        state = RandomEventState(
            chat_id=chat_id,
            prize=prize,
            win_chance=win_chance,
            max_winners=max_winners,
        )
        self._states[chat_id] = state
        pct_str = f"{win_chance * 100:.1f}"
        text = message_manager.render(
            "RANDOM_START",
            prize=prize,
            chance=pct_str,
            max_winners=max_winners,
        )
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        await self._logger.log_event(
            "РОЗЫГРЫШ",
            f"Запущен в чате {chat_id} | Приз: {prize} | Шанс: {pct_str}% | Победителей: {max_winners}"
        )

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

        # Prevent the same person from winning twice in the same event
        if username in state.winners:
            return

        won = False
        all_done = False

        async with self._lock(chat_id):
            if state.finished:
                return
            state.total_attempts += 1
            won = random.random() < state.win_chance
            if won:
                state.winners.append(username)
                if state.all_winners_found:
                    state.finished = True
                    all_done = True

        if won:
            remaining_slots = state.max_winners - state.winners_found
            text = message_manager.render(
                "RANDOM_WIN",
                username=username,
                prize=state.prize,
                attempts=state.total_attempts,
            )
            # Append remaining winners info if multi-winner event still running
            if not all_done:
                text += (
                    f"\n\n{remaining_slots} место(мест) ещё не разыграно! "
                    f"Продолжаем — пишите в чат!"
                )

            try:
                await update.message.reply_text(text, parse_mode="HTML")
            except Exception as e:
                log.warning("Ошибка отправки сообщения о победе в розыгрыше: %s", e)

            await self._logger.log_winner("РОЗЫГРЫШ", username, state.prize)

            if all_done:
                # All winners found — send final summary
                await self._send_all_winners_summary(context.bot, state)
                self._states.pop(chat_id, None)

    async def _send_all_winners_summary(self, bot, state: RandomEventState) -> None:
        """Send a final message listing all winners when event completes."""
        winners_list = "\n".join(
            f"🏅 {i+1}. @{w}" for i, w in enumerate(state.winners)
        )
        text = message_manager.render(
            "RANDOM_ALL_WINNERS",
            prize=state.prize,
            winners_list=winners_list,
        )
        try:
            await bot.send_message(chat_id=state.chat_id, text=text, parse_mode="HTML")
        except Exception as e:
            log.error("Не удалось отправить итоговое сообщение розыгрыша: %s", e)


async def _is_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id, update.effective_user.id
        )
        return member.status in ("administrator", "creator")
    except Exception:
        return False
