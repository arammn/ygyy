"""
casino.py — Система казино.

Использует НАСТОЯЩИЙ Telegram слот-машину (эмодзи 🎰 / dice с emoji="🎰").
Telegram сам крутит барабаны и возвращает значение 1–64.
Значение 64 соответствует комбинации 7-7-7 (джекпот).

Как участвовать:
  Отправьте в группу эмодзи 🎰 через меню стикеров Telegram.
  Бот видит реальный результат слота и объявляет победителя при 7-7-7 (значение 64).

Команды (только администраторам, в группе):
  /startcasino [описание приза...]
  /stopcasino
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_IDS
from ignore_system import IgnoreSystem
from logger import BotLogger
from message_manager import message_manager

log = logging.getLogger(__name__)

# Telegram slot machine: emoji="🎰", value 64 == 7|7|7 (jackpot)
SLOT_EMOJI = "🎰"
JACKPOT_VALUE = 64  # The only value that gives 7-7-7 in Telegram's slot machine

# Mapping of slot value → (reel1, reel2, reel3) for display purposes
# Telegram slot machine reels cycle: BAR, GRAPE, LEMON, SEVEN (simplified)
# We only need to know value 64 = 777; for near-miss we check if value >= 60
# (values 60-63 have two 7s based on Telegram's internal mapping)
NEAR_MISS_THRESHOLD = 60  # values 60-63 are "almost" jackpot (two 7s visible)


@dataclass
class CasinoState:
    chat_id: int
    prize: str
    finished: bool = False
    total_rolls: int = 0


class CasinoEvent:
    def __init__(self, bot_logger: BotLogger, ignore_system: IgnoreSystem) -> None:
        self._logger = bot_logger
        self._ignore = ignore_system
        self._states: dict[int, CasinoState] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def is_active(self, chat_id: int) -> bool:
        return chat_id in self._states and not self._states[chat_id].finished

    def active_chats(self) -> list[int]:
        return [cid for cid, s in self._states.items() if not s.finished]

    def get_state(self, chat_id: int) -> Optional[CasinoState]:
        return self._states.get(chat_id)

    def _lock(self, chat_id: int) -> asyncio.Lock:
        if chat_id not in self._locks:
            self._locks[chat_id] = asyncio.Lock()
        return self._locks[chat_id]

    async def cmd_start_casino(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not user or user.id not in ADMIN_IDS:
            return
        if self.is_active(update.effective_chat.id):
            await update.message.reply_text("⚠️ Казино уже запущено!")
            return
        args = context.args or []
        prize = " ".join(args) if args else "Сюрприз"
        await self._start(update, context, prize)

    async def cmd_stop_casino(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not user or user.id not in ADMIN_IDS:
            return
        chat_id = update.effective_chat.id
        if not self.is_active(chat_id):
            await update.message.reply_text("Казино не запущено.")
            return
        state = self._states.pop(chat_id, None)
        if state:
            state.finished = True
        await update.message.reply_text("🛑 Казино остановлено администратором.")

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

    async def force_stop(self, chat_id: int, bot) -> bool:
        if not self.is_active(chat_id):
            return False
        state = self._states.pop(chat_id, None)
        if state:
            state.finished = True
        try:
            await bot.send_message(
                chat_id=chat_id,
                text="🛑 Казино остановлено администратором."
            )
        except Exception:
            pass
        return True

    # ── Основная логика ───────────────────────────────────────────────────

    async def _start(self, update: Update, context: ContextTypes.DEFAULT_TYPE, prize: str) -> None:
        chat_id = update.effective_chat.id
        state = CasinoState(chat_id=chat_id, prize=prize)
        self._states[chat_id] = state
        text = message_manager.render("CASINO_START", prize=prize)
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        await self._logger.log_event("КАЗИНО", f"Запущено в чате {chat_id} | Приз: {prize}")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handles ALL messages in the group while casino is active.
        Specifically watches for Telegram dice messages with emoji="🎰".
        The bot reads the REAL slot value assigned by Telegram servers.
        Value 64 = 7|7|7 = jackpot.
        """
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

        message = update.message
        if not message:
            return

        # ── Only process Telegram slot machine dice messages ──────────────
        # update.message.dice is set when the message is a dice/slot emoji
        dice = message.dice
        if dice is None:
            # Not a dice message — ignore (only slot machine counts)
            return

        if dice.emoji != SLOT_EMOJI:
            # It's a dice/dart/basketball etc., not the slot machine
            return

        slot_value = dice.value  # Integer 1–64, set by Telegram servers
        username = user.username or user.first_name
        won = (slot_value == JACKPOT_VALUE)

        async with self._lock(chat_id):
            if state.finished:
                return
            state.total_rolls += 1
            if won:
                state.finished = True

        if won:
            text = message_manager.render(
                "CASINO_WIN",
                username=username,
                prize=state.prize,
            )
            try:
                await message.reply_text(text, parse_mode="HTML")
            except Exception as e:
                log.warning("Ошибка отправки сообщения о победе в казино: %s", e)
            await self._logger.log_winner("КАЗИНО", username, state.prize)
            self._states.pop(chat_id, None)
        else:
            # Near-miss: values 60-63 have two 7s showing
            if slot_value >= NEAR_MISS_THRESHOLD:
                text = message_manager.render(
                    "CASINO_NEAR_MISS",
                    username=username,
                )
                try:
                    await message.reply_text(text, parse_mode="HTML")
                except Exception as e:
                    log.warning("Ошибка отправки сообщения о почти-победе в казино: %s", e)


async def _is_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id, update.effective_user.id
        )
        return member.status in ("administrator", "creator")
    except Exception:
        return False
