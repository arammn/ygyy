import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS = [
        int(uid.strip())
        for uid in os.getenv("ADMIN_IDS", "").split(",")
        if uid.strip().isdigit()
    ]
    DEFAULT_TIMER = int(os.getenv("DEFAULT_TIMER", "180"))
    DEFAULT_STARS = [
        int(s.strip())
        for s in os.getenv("DEFAULT_STARS", "1,2,3").split(",")
        if s.strip().isdigit()
    ]
    DB_PATH = os.getenv("DB_PATH", "data/bot.db")
    MIN_TIMER = 10
    MAX_TIMER = 3600
    MIN_STARS = 1
    MAX_STARS = 999

    @classmethod
    def validate(cls) -> bool:
        if not cls.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is required in .env file")
        if not cls.ADMIN_IDS:
            raise ValueError("ADMIN_IDS is required in .env file")
        return True
