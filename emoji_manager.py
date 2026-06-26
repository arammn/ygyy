"""
emoji_manager.py — Кастомные эмодзи с поддержкой Telegram Premium анимированных эмодзи.

Администраторы могут задавать:
  • Обычный Unicode-эмодзи:      /setemoji EMOJI_WIN 🏆
  • Telegram Premium эмодзи:     /setemoji EMOJI_WIN tg:5413572157940735873:🏆
    Формат:  tg:<emoji_id>:<запасной_символ>
    При рендеринге превратится в <tg-emoji emoji-id="...">🏆</tg-emoji>

ВАЖНО: Telegram Premium эмодзи работают только в сообщениях с parse_mode="HTML".
Бот должен быть участником группы. Анимация видна только пользователям с Premium.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from config import EMOJI_FILE, DEFAULT_EMOJIS

log = logging.getLogger(__name__)

TG_PREFIX = "tg:"


def _encode_premium(emoji_id: str, fallback: str) -> str:
    """
    Формирует HTML-тег для Telegram Premium анимированного эмодзи.
    Пример: <tg-emoji emoji-id="5413572157940735873">🏆</tg-emoji>
    """
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


def parse_emoji_value(raw: str) -> str:
    """
    Принимает ввод администратора и конвертирует в формат хранения.
    """
    raw = raw.strip()
    if raw.startswith(TG_PREFIX):
        rest = raw[len(TG_PREFIX):]
        colon_idx = rest.find(":")
        if colon_idx > 0:
            emoji_id = rest[:colon_idx].strip()
            fallback = rest[colon_idx + 1:].strip()
            if emoji_id.isdigit() and fallback:
                return _encode_premium(emoji_id, fallback)
    return raw


def is_premium_emoji(stored_value: str) -> bool:
    """Проверяет, является ли хранимое значение Premium-эмодзи."""
    return stored_value.startswith('<tg-emoji')


class EmojiManager:
    def __init__(self) -> None:
        self._file: Path = EMOJI_FILE
        self._emojis: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        if self._file.exists():
            try:
                data = json.loads(self._file.read_text(encoding="utf-8"))
                return {**DEFAULT_EMOJIS, **data}
            except Exception as e:
                log.warning("Не удалось загрузить emojis.json: %s", e)
        return dict(DEFAULT_EMOJIS)

    def _save(self) -> None:
        self._file.write_text(
            json.dumps(self._emojis, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get(self, key: str) -> str:
        return self._emojis.get(key, DEFAULT_EMOJIS.get(key, "❓"))

    def set(self, key: str, raw_value: str) -> None:
        self._emojis[key] = parse_emoji_value(raw_value)
        self._save()

    def set_raw(self, key: str, value: str) -> None:
        self._emojis[key] = value
        self._save()

    def render(self, text: str) -> str:
        for key, emoji_val in self._emojis.items():
            text = text.replace(f"{{{key}}}", emoji_val)
        return text

    def all_emojis(self) -> dict[str, str]:
        return dict(self._emojis)

    def display_value(self, key: str) -> str:
        return self._emojis.get(key, DEFAULT_EMOJIS.get(key, "❓"))

    def display_value_safe(self, key: str) -> str:
        val = self.display_value(key)
        if is_premium_emoji(val):
            import re
            m = re.match(r'<tg-emoji emoji-id="(\d+)">(.+?)</tg-emoji>', val)
            if m:
                return f"tg:{m.group(1)}:{m.group(2)}"
        return val


emoji_manager = EmojiManager()
