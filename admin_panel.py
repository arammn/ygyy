"""
admin_panel.py — Полный интерфейс меню администратора.

Команды (только для администраторов, в личном чате):
  /start    — главное меню
  /menu     — показать меню
  /logs     — последние логи
  /setemoji KEY emoji
  /setmessage KEY текст
  /resetmessage KEY

Меню:
  📊 Активные события  — управление запущенными событиями
  🎨 Настройки эмодзи  — изменение эмодзи
  ✏️ Шаблоны сообщений — редактирование шаблонов
  📜 Логи              — просмотр логов
"""

from __future__ import annotations

import logging
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import ADMIN_IDS
from emoji_manager import emoji_manager
from logger import BotLogger
from ignore_system import IgnoreSystem
from message_manager import message_manager

log = logging.getLogger(__name__)

# ── Состояния потоков ввода ───────────────────────────────────────────────────
STATE_NONE          = "none"
STATE_SET_EMOJI     = "set_emoji"
STATE_SET_MESSAGE   = "set_message"
STATE_EDIT_PRIZE    = "edit_prize"
STATE_EDIT_DURATION = "edit_duration"   # теперь для установки абсолютной длительности
STATE_EDIT_CHANCE   = "edit_chance"


def _is_admin(update: Update) -> bool:
    user = update.effective_user
    return user is not None and user.id in ADMIN_IDS


def _main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Активные события", callback_data="menu:active_events")],
        [InlineKeyboardButton("🎨 Настройки эмодзи", callback_data="menu:emojis")],
        [InlineKeyboardButton("✏️ Шаблоны сообщений", callback_data="menu:messages")],
        [InlineKeyboardButton("📜 Логи", callback_data="menu:logs")],
    ])


class AdminPanel:
    def __init__(self, bot_logger: BotLogger, ignore_system: IgnoreSystem) -> None:
        self._logger = bot_logger
        self._ignore = ignore_system

    # ─────────────────────────────────────────────────────────────────────────
    # Command handlers
    # ─────────────────────────────────────────────────────────────────────────

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_admin(update):
            return
        context.user_data["state"] = STATE_NONE
        await update.message.reply_text(
            "👋 <b>Добро пожаловать в панель администратора!</b>\n\n"
            "Используйте меню ниже для управления ботом.",
            parse_mode="HTML",
            reply_markup=_main_menu_keyboard(),
        )

    async def cmd_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_admin(update):
            return
        context.user_data["state"] = STATE_NONE
        await update.message.reply_text(
            "⚙️ <b>Меню администратора</b>",
            parse_mode="HTML",
            reply_markup=_main_menu_keyboard(),
        )

    async def cmd_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_admin(update):
            return
        logs = self._logger.get_recent_logs(50)
        if len(logs) > 4000:
            logs = "...\n" + logs[-4000:]
        await update.message.reply_text(
            f"📜 <b>Последние логи:</b>\n\n<pre>{logs}</pre>",
            parse_mode="HTML",
        )

    async def cmd_setemoji(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_admin(update):
            return
        args = context.args or []
        if len(args) < 2:
            await update.message.reply_text(
                "Использование: /setemoji KEY emoji\n"
                "Пример: /setemoji EMOJI_WIN 🏆\n"
                "Premium: /setemoji EMOJI_WIN tg:5413572157940735873:🏆"
            )
            return
        key = args[0].upper()
        value = " ".join(args[1:])
        from config import DEFAULT_EMOJIS
        if key not in DEFAULT_EMOJIS:
            await update.message.reply_text(f"❌ Неизвестный ключ: {key}")
            return
        emoji_manager.set(key, value)
        await update.message.reply_text(f"✅ {key} обновлён.")

    async def cmd_setmessage(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_admin(update):
            return
        args = context.args or []
        if len(args) < 2:
            await update.message.reply_text(
                "Использование: /setmessage KEY текст шаблона\n"
                "Пример: /setmessage AUCTION_WIN 🏆 Победитель: @{winner}!"
            )
            return
        key = args[0].upper()
        value = " ".join(args[1:]).replace("\\n", "\n")
        if message_manager.set(key, value):
            await update.message.reply_text(f"✅ Шаблон {key} обновлён.")
        else:
            await update.message.reply_text(f"❌ Неизвестный ключ: {key}")

    async def cmd_resetmessage(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_admin(update):
            return
        args = context.args or []
        if not args:
            await update.message.reply_text("Использование: /resetmessage KEY")
            return
        key = args[0].upper()
        if message_manager.reset(key):
            await update.message.reply_text(f"✅ Шаблон {key} сброшен к значению по умолчанию.")
        else:
            await update.message.reply_text(f"❌ Неизвестный ключ: {key}")

    # ─────────────────────────────────────────────────────────────────────────
    # Text input handler (for edit flows)
    # ─────────────────────────────────────────────────────────────────────────

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_admin(update):
            return
        state = context.user_data.get("state", STATE_NONE)
        text = update.message.text or ""

        if state == STATE_SET_EMOJI:
            key = context.user_data.get("edit_key", "")
            emoji_manager.set(key, text.strip())
            context.user_data["state"] = STATE_NONE
            await update.message.reply_text(
                f"✅ {key} обновлён: {emoji_manager.display_value_safe(key)}",
                reply_markup=_main_menu_keyboard(),
            )

        elif state == STATE_SET_MESSAGE:
            key = context.user_data.get("edit_key", "")
            value = text.replace("\\n", "\n")
            if message_manager.set(key, value):
                context.user_data["state"] = STATE_NONE
                await update.message.reply_text(
                    f"✅ Шаблон {key} обновлён.",
                    reply_markup=_main_menu_keyboard(),
                )
            else:
                await update.message.reply_text(f"❌ Неизвестный ключ: {key}")

        elif state == STATE_EDIT_PRIZE:
            chat_id = context.user_data.get("target_chat_id")
            event_type = context.user_data.get("event_type", "")
            if chat_id:
                success = await self._set_prize(context, chat_id, event_type, text.strip())
                context.user_data["state"] = STATE_NONE
                if success:
                    await update.message.reply_text(
                        f"✅ Приз обновлён: {text.strip()}",
                        reply_markup=_main_menu_keyboard(),
                    )
                else:
                    await update.message.reply_text("❌ Не удалось обновить приз.")

        elif state == STATE_EDIT_DURATION:
            # Теперь это установка новой базовой длительности аукциона
            chat_id = context.user_data.get("target_chat_id")
            if chat_id and text.strip().isdigit():
                new_duration = int(text.strip())
                auction = context.bot_data.get("auction")
                if auction:
                    success = await auction.set_duration(chat_id, new_duration, context.bot)
                    context.user_data["state"] = STATE_NONE
                    if success:
                        await update.message.reply_text(
                            f"✅ Длительность изменена на {new_duration} секунд.",
                            reply_markup=_main_menu_keyboard(),
                        )
                    else:
                        await update.message.reply_text("❌ Не удалось изменить длительность.")
                else:
                    await update.message.reply_text("❌ Аукцион не найден.")
            else:
                await update.message.reply_text("❌ Введите целое положительное число секунд.")

        elif state == STATE_EDIT_CHANCE:
            chat_id = context.user_data.get("target_chat_id")
            val = text.strip().rstrip("%")
            if chat_id and val.replace(".", "").isdigit():
                pct = float(val)
                random_event = context.bot_data.get("random_event")
                if random_event:
                    await random_event.edit_chance(chat_id, pct)
                context.user_data["state"] = STATE_NONE
                await update.message.reply_text(
                    f"✅ Шанс обновлён: {pct}%",
                    reply_markup=_main_menu_keyboard(),
                )
            else:
                await update.message.reply_text("❌ Введите число (например: 10 или 10%)")

        else:
            await update.message.reply_text(
                "⚙️ <b>Меню администратора</b>",
                parse_mode="HTML",
                reply_markup=_main_menu_keyboard(),
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Callback query handler
    # ─────────────────────────────────────────────────────────────────────────

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query:
            return
        await query.answer()

        if not _is_admin(update):
            return

        data = query.data or ""

        # ── Main menu ────────────────────────────────────────────────────────
        if data == "menu:main":
            await query.edit_message_text(
                "⚙️ <b>Меню администратора</b>",
                parse_mode="HTML",
                reply_markup=_main_menu_keyboard(),
            )

        elif data == "menu:logs":
            logs = self._logger.get_recent_logs(30)
            if len(logs) > 3500:
                logs = "...\n" + logs[-3500:]
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="menu:main")
            ]])
            await query.edit_message_text(
                f"📜 <b>Последние логи:</b>\n\n<pre>{logs}</pre>",
                parse_mode="HTML",
                reply_markup=kb,
            )

        # ── Emoji settings ───────────────────────────────────────────────────
        elif data == "menu:emojis":
            await self._show_emoji_menu(query)

        elif data.startswith("emoji:edit:"):
            key = data.split(":", 2)[2]
            context.user_data["state"] = STATE_SET_EMOJI
            context.user_data["edit_key"] = key
            current = emoji_manager.display_value_safe(key)
            await query.edit_message_text(
                f"🎨 Редактирование <b>{key}</b>\n\n"
                f"Текущее значение: <code>{current}</code>\n\n"
                f"Отправьте новое значение:\n"
                f"• Обычный эмодзи: <code>🏆</code>\n"
                f"• Premium эмодзи: <code>tg:ID:🏆</code>",
                parse_mode="HTML",
            )

        # ── Message templates ────────────────────────────────────────────────
        elif data == "menu:messages":
            await self._show_message_menu(query)

        elif data.startswith("msg:edit:"):
            key = data.split(":", 2)[2]
            context.user_data["state"] = STATE_SET_MESSAGE
            context.user_data["edit_key"] = key
            current = message_manager.get_raw(key)
            await query.edit_message_text(
                f"✏️ Редактирование <b>{key}</b>\n\n"
                f"Текущий шаблон:\n<pre>{current[:500]}</pre>\n\n"
                f"Отправьте новый шаблон (используйте \\n для переноса строки):",
                parse_mode="HTML",
            )

        elif data.startswith("msg:reset:"):
            key = data.split(":", 2)[2]
            message_manager.reset(key)
            await query.edit_message_text(
                f"✅ Шаблон {key} сброшен.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 К шаблонам", callback_data="menu:messages")
                ]]),
            )

        # ── Active events ────────────────────────────────────────────────────
        elif data == "menu:active_events":
            await self._show_active_events(query, context)

        elif data.startswith("event:manage:"):
            parts = data.split(":")
            event_type = parts[2]
            chat_id = int(parts[3])
            await self._show_event_manage(query, context, event_type, chat_id)

        elif data.startswith("event:stop:"):
            parts = data.split(":")
            event_type = parts[2]
            chat_id = int(parts[3])
            success = await self._force_stop(context, event_type, chat_id)
            result = "✅ Событие остановлено." if success else "❌ Событие уже завершено."
            await query.edit_message_text(
                result,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 К событиям", callback_data="menu:active_events")
                ]]),
            )

        elif data.startswith("event:prize:"):
            parts = data.split(":")
            event_type = parts[2]
            chat_id = int(parts[3])
            context.user_data["state"] = STATE_EDIT_PRIZE
            context.user_data["target_chat_id"] = chat_id
            context.user_data["event_type"] = event_type
            await query.edit_message_text(
                f"✏️ Введите новый приз для <b>{event_type}</b> в чате {chat_id}:",
                parse_mode="HTML",
            )

        elif data.startswith("event:extend:"):
            # Быстрое продление на 60 секунд (существующая кнопка)
            parts = data.split(":")
            chat_id = int(parts[2])
            auction = context.bot_data.get("auction")
            if auction:
                await auction.edit_duration(chat_id, 60)
            await query.edit_message_text(
                "✅ Аукцион продлён на 60 секунд.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 К событиям", callback_data="menu:active_events")
                ]]),
            )

        elif data.startswith("event:set_duration:"):
            # Новая кнопка: установка абсолютной длительности
            parts = data.split(":")
            chat_id = int(parts[2])
            context.user_data["state"] = STATE_EDIT_DURATION
            context.user_data["target_chat_id"] = chat_id
            await query.edit_message_text(
                "⏱ Введите новую длительность аукциона в секундах (целое число):"
            )

        elif data.startswith("event:chance:"):
            parts = data.split(":")
            chat_id = int(parts[2])
            context.user_data["state"] = STATE_EDIT_CHANCE
            context.user_data["target_chat_id"] = chat_id
            await query.edit_message_text(
                "🎲 Введите новый шанс победы в % (например: 10 или 10%):"
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    async def _show_emoji_menu(self, query) -> None:
        from config import DEFAULT_EMOJIS
        buttons = []
        for key in sorted(DEFAULT_EMOJIS.keys()):
            display = emoji_manager.display_value_safe(key)
            buttons.append([
                InlineKeyboardButton(
                    f"{display}  {key}",
                    callback_data=f"emoji:edit:{key}",
                )
            ])
        buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="menu:main")])
        await query.edit_message_text(
            "🎨 <b>Настройки эмодзи</b>\n\nВыберите эмодзи для редактирования:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    async def _show_message_menu(self, query) -> None:
        keys = message_manager.all_keys()
        buttons = []
        for key in keys:
            buttons.append([
                InlineKeyboardButton(f"✏️ {key}", callback_data=f"msg:edit:{key}"),
                InlineKeyboardButton("↩️", callback_data=f"msg:reset:{key}"),
            ])
        buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="menu:main")])
        await query.edit_message_text(
            "✏️ <b>Шаблоны сообщений</b>\n\n"
            "Нажмите ✏️ для редактирования или ↩️ для сброса:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    async def _show_active_events(self, query, context) -> None:
        auction      = context.bot_data.get("auction")
        casino       = context.bot_data.get("casino")
        random_event = context.bot_data.get("random_event")

        buttons = []
        has_any = False

        if auction:
            for chat_id in auction.active_chats():
                state = auction.get_state(chat_id)
                label = f"🔨 Аукцион | чат {chat_id} | {state.prize[:20]}"
                buttons.append([InlineKeyboardButton(
                    label, callback_data=f"event:manage:auction:{chat_id}"
                )])
                has_any = True

        if casino:
            for chat_id in casino.active_chats():
                state = casino.get_state(chat_id)
                label = f"🎰 Казино | чат {chat_id} | {state.prize[:20]}"
                buttons.append([InlineKeyboardButton(
                    label, callback_data=f"event:manage:casino:{chat_id}"
                )])
                has_any = True

        if random_event:
            for chat_id in random_event.active_chats():
                state = random_event.get_state(chat_id)
                label = f"🍀 Розыгрыш | чат {chat_id} | {state.prize[:20]}"
                buttons.append([InlineKeyboardButton(
                    label, callback_data=f"event:manage:random:{chat_id}"
                )])
                has_any = True

        if not has_any:
            buttons.append([InlineKeyboardButton("— Нет активных событий —", callback_data="menu:active_events")])

        buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="menu:main")])
        await query.edit_message_text(
            "📊 <b>Активные события</b>\n\nВыберите событие для управления:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    async def _show_event_manage(self, query, context, event_type: str, chat_id: int) -> None:
        buttons = [
            [InlineKeyboardButton("✏️ Изменить приз", callback_data=f"event:prize:{event_type}:{chat_id}")],
        ]

        if event_type == "auction":
            buttons.append([InlineKeyboardButton("⏱ Продлить +60с", callback_data=f"event:extend:{chat_id}")])
            buttons.append([InlineKeyboardButton("⏱ Изменить длительность", callback_data=f"event:set_duration:{chat_id}")])
        elif event_type == "random":
            buttons.append([InlineKeyboardButton("🎲 Изменить шанс %", callback_data=f"event:chance:{chat_id}")])

        buttons.append([InlineKeyboardButton("🛑 Остановить", callback_data=f"event:stop:{event_type}:{chat_id}")])
        buttons.append([InlineKeyboardButton("🔙 К событиям", callback_data="menu:active_events")])

        await query.edit_message_text(
            f"⚙️ <b>Управление событием</b>\n\n"
            f"Тип: <b>{event_type}</b>\n"
            f"Чат: <code>{chat_id}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    async def _force_stop(self, context, event_type: str, chat_id: int) -> bool:
        bot = context.bot
        if event_type == "auction":
            ev = context.bot_data.get("auction")
        elif event_type == "casino":
            ev = context.bot_data.get("casino")
        else:
            ev = context.bot_data.get("random_event")
        if ev:
            return await ev.force_stop(chat_id, bot)
        return False

    async def _set_prize(self, context, chat_id: int, event_type: str, prize: str) -> bool:
        if event_type == "auction":
            ev = context.bot_data.get("auction")
        elif event_type == "casino":
            ev = context.bot_data.get("casino")
        else:
            ev = context.bot_data.get("random_event")
        if ev:
            return await ev.edit_prize(chat_id, prize)
        return False