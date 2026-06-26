"""
message_manager.py — Редактируемые шаблоны сообщений.

Все пользовательские строки хранятся в messages.json и могут быть изменены
через админ-панель (/setmessage KEY новый текст).

Плейсхолдеры в шаблонах:
  {EMOJI_*}    → заменяются EmojiManager
  {переменная} → заменяются динамическими значениями при рендеринге

Использование:
    msg = message_manager.render("AUCTION_WIN",
              winner="alice", prize="500 Stars", bid_count=42)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from config import MESSAGES_FILE, DEFAULT_MESSAGES
from emoji_manager import emoji_manager

log = logging.getLogger(__name__)


class MessageManager:
    def __init__(self) -> None:
        self._file: Path = MESSAGES_FILE
        self._messages: dict[str, str] = self._load()

    # ── Персистентность ───────────────────────────────────────────────────

    def _load(self) -> dict[str, str]:
        if self._file.exists():
            try:
                data = json.loads(self._file.read_text(encoding="utf-8"))
                return {**DEFAULT_MESSAGES, **data}
            except Exception as e:
                log.warning("Не удалось загрузить messages.json: %s", e)
        return dict(DEFAULT_MESSAGES)

    def _save(self) -> None:
        self._file.write_text(
            json.dumps(self._messages, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── Публичный API ─────────────────────────────────────────────────────

    def get_raw(self, key: str) -> str:
        return self._messages.get(key, DEFAULT_MESSAGES.get(key, f"[Нет сообщения: {key}]"))

    def set(self, key: str, value: str) -> bool:
        if key not in DEFAULT_MESSAGES:
            return False
        self._messages[key] = value
        self._save()
        return True

    def reset(self, key: str) -> bool:
        if key not in DEFAULT_MESSAGES:
            return False
        self._messages[key] = DEFAULT_MESSAGES[key]
        self._save()
        return True

    def render(self, key: str, **kwargs) -> str:
        """
        Рендерит шаблон сообщения:
          1. Получает сырой шаблон
          2. Заменяет {EMOJI_*} через emoji_manager
          3. Заменяет оставшиеся {переменные} значениями из kwargs
        """
        raw = self.get_raw(key)
        text = emoji_manager.render(raw)
        try:
            text = text.format(**kwargs)
        except KeyError as e:
            log.warning("Шаблон '%s' не содержит ключ %s", key, e)
        except Exception as e:
            log.warning("Ошибка рендеринга шаблона '%s': %s", key, e)
        return text

    def all_keys(self) -> list[str]:
        return sorted(DEFAULT_MESSAGES.keys())

    def reload(self) -> None:
        self._messages = self._load()


message_manager = MessageManager()
