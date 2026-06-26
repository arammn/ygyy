"""
ignore_system.py — Управление пользователями, исключёнными из всех событий.

Команды (только для администраторов):
  /ignore @username
  /unignore @username
  /ignorelist
"""

from __future__ import annotations

import logging
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from config import IGNORE_FILE, ADMIN_IDS

log = logging.getLogger(__name__)


class IgnoreSystem:
    def __init__(self) -> None:
        self._file: Path = IGNORE_FILE
        self._ignored: set[str] = self._load()

    def _load(self) -> set[str]:
        if self._file.exists():
            return {
                line.strip().lstrip("@").lower()
                for line in self._file.read_text().splitlines()
                if line.strip()
            }
        return set()

    def _save(self) -> None:
        self._file.write_text("\n".join(sorted(self._ignored)), encoding="utf-8")

    def add(self, username: str) -> bool:
        key = username.lstrip("@").lower()
        if key in self._ignored:
            return False
        self._ignored.add(key)
        self._save()
        return True

    def remove(self, username: str) -> bool:
        key = username.lstrip("@").lower()
        if key not in self._ignored:
            return False
        self._ignored.discard(key)
        self._save()
        return True

    def is_ignored(self, username: str | None) -> bool:
        if not username:
            return False
        return username.lstrip("@").lower() in self._ignored

    def get_list(self) -> list[str]:
        return sorted(self._ignored)

    def should_skip(self, update: Update) -> bool:
        user = update.effective_user
        if not user:
            return True
        return self.is_ignored(user.username)

    async def cmd_ignore(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_admin(update):
            return
        args = context.args
        if not args:
            await update.message.reply_text("Использование: /ignore @username")
            return
        username = args[0].lstrip("@")
        if self.add(username):
            await update.message.reply_text(f"🚫 @{username} добавлен в список игнора.")
            bot_logger = context.bot_data.get("logger")
            if bot_logger:
                admin_name = update.effective_user.username or str(update.effective_user.id)
                await bot_logger.log_ignore_action("ИГНОР", username, admin_name)
        else:
            await update.message.reply_text(f"⚠️ @{username} уже в списке игнора.")

    async def cmd_unignore(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_admin(update):
            return
        args = context.args
        if not args:
            await update.message.reply_text("Использование: /unignore @username")
            return
        username = args[0].lstrip("@")
        if self.remove(username):
            await update.message.reply_text(f"✅ @{username} удалён из списка игнора.")
            bot_logger = context.bot_data.get("logger")
            if bot_logger:
                admin_name = update.effective_user.username or str(update.effective_user.id)
                await bot_logger.log_ignore_action("РАЗИГНОР", username, admin_name)
        else:
            await update.message.reply_text(f"⚠️ @{username} не находится в списке игнора.")

    async def cmd_ignorelist(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_admin(update):
            return
        items = self.get_list()
        if not items:
            await update.message.reply_text("🚫 Список игнора пуст.")
            return
        lines = "\n".join(f"• @{u}" for u in items)
        await update.message.reply_text(
            f"🚫 <b>Список игнора</b>\n\n{lines}", parse_mode="HTML"
        )


def _is_admin(update: Update) -> bool:
    user = update.effective_user
    return user is not None and user.id in ADMIN_IDS
