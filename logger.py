"""
logger.py — Централизованное логирование бота.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from config import LOG_FILE, ADMIN_IDS

log = logging.getLogger(__name__)


class BotLogger:
    def __init__(self) -> None:
        self._file: Path = LOG_FILE
        self._file.touch(exist_ok=True)
        self._bot = None

    def attach_bot(self, bot) -> None:
        self._bot = bot

    def _write(self, level: str, message: str) -> None:
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        line = f"[{ts}] [{level}] {message}\n"
        try:
            with self._file.open("a", encoding="utf-8") as f:
                f.write(line)
        except Exception as e:
            log.error("Не удалось записать лог: %s", e)

    async def log(self, message: str, notify_admins: bool = True) -> None:
        self._write("INFO", message)
        log.info(message)
        if notify_admins and self._bot:
            await self._notify_admins(f"ℹ️ {message}")

    async def log_event(self, event_type: str, message: str) -> None:
        full = f"[{event_type}] {message}"
        self._write("EVENT", full)
        log.info(full)
        if self._bot:
            await self._notify_admins(f"📊 [{event_type}] {message}")

    async def log_winner(self, event_type: str, username: str, prize: str) -> None:
        msg = f"ПОБЕДИТЕЛЬ в {event_type}: @{username} выиграл '{prize}'"
        self._write("WINNER", msg)
        log.info(msg)
        if self._bot:
            await self._notify_admins(f"🏆 {msg}")

    async def log_error(self, message: str) -> None:
        self._write("ERROR", message)
        log.error(message)
        if self._bot:
            await self._notify_admins(f"❌ ОШИБКА: {message}")

    async def log_ignore_action(self, action: str, username: str, by_admin: str) -> None:
        msg = f"{action}: @{username} администратором @{by_admin}"
        self._write("IGNORE", msg)
        log.info(msg)

    def get_recent_logs(self, lines: int = 50) -> str:
        try:
            content = self._file.read_text(encoding="utf-8").splitlines()
            recent = content[-lines:] if len(content) > lines else content
            return "\n".join(recent) if recent else "Логов пока нет."
        except Exception:
            return "Не удалось прочитать логи."

    async def _notify_admins(self, message: str) -> None:
        if not self._bot:
            return
        for admin_id in ADMIN_IDS:
            try:
                await self._bot.send_message(chat_id=admin_id, text=message, parse_mode="HTML")
            except Exception as e:
                log.warning("Не удалось уведомить администратора %s: %s", admin_id, e)
