"""Async SQLite database operations."""
import aiosqlite, json, logging, os
from typing import Optional, Dict, Any, List
from config import Config

logger = logging.getLogger(__name__)

class Database:
    _instance = None
    _db = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def initialize(self):
        os.makedirs(os.path.dirname(Config.DB_PATH), exist_ok=True)
        self._db = await aiosqlite.connect(Config.DB_PATH)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._create_tables()
        logger.info("Database initialized successfully")

    async def _create_tables(self):
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER UNIQUE NOT NULL,
                title TEXT NOT NULL,
                type TEXT NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER UNIQUE NOT NULL,
                active BOOLEAN DEFAULT 0,
                timer_duration INTEGER NOT NULL,
                allowed_stars TEXT NOT NULL,
                description TEXT DEFAULT '',
                current_leader_id INTEGER,
                leader_name TEXT,
                timer_start REAL,
                job_name TEXT,
                bid_count INTEGER DEFAULT 0,
                total_stars INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES groups(chat_id)
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS auction_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                winner_id INTEGER,
                winner_name TEXT,
                description TEXT DEFAULT '',
                total_bids INTEGER DEFAULT 0,
                total_stars INTEGER DEFAULT 0,
                ended_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS lucky_draws (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER UNIQUE NOT NULL,
                active BOOLEAN DEFAULT 0,
                chance INTEGER NOT NULL,
                prize TEXT DEFAULT '',
                photo_file_id TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES groups(chat_id)
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS dice_games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER UNIQUE NOT NULL,
                active BOOLEAN DEFAULT 0,
                dice_emoji TEXT NOT NULL,
                winning_value INTEGER NOT NULL,
                prize TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES groups(chat_id)
            )
        """)
        try:
            await self._db.execute("ALTER TABLE games ADD COLUMN description TEXT DEFAULT ''")
        except: pass
        try:
            await self._db.execute("ALTER TABLE auction_history ADD COLUMN description TEXT DEFAULT ''")
        except: pass
        try:
            await self._db.execute("ALTER TABLE lucky_draws ADD COLUMN photo_file_id TEXT DEFAULT NULL")
        except: pass
        try:
            await self._db.execute("ALTER TABLE games ADD COLUMN bid_count INTEGER DEFAULT 0")
        except: pass
        try:
            await self._db.execute("ALTER TABLE games ADD COLUMN total_stars INTEGER DEFAULT 0")
        except: pass
        await self._db.commit()

    async def upsert_group(self, chat_id: int, title: str, chat_type: str):
        await self._db.execute(
            """INSERT INTO groups (chat_id, title, type) VALUES (?,?,?)
               ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, type=excluded.type""",
            (chat_id, title, chat_type)
        )
        await self._db.commit()

    async def get_all_groups(self) -> List[Dict[str, Any]]:
        cur = await self._db.execute("SELECT chat_id, title, type, added_at FROM groups ORDER BY added_at DESC")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def create_active_game(self, chat_id, timer, stars, description=""):
        stars_json = json.dumps(stars)
        await self._db.execute(
            """INSERT INTO games (chat_id, active, timer_duration, allowed_stars, description, bid_count, total_stars)
               VALUES (?,1,?,?,?,0,0)
               ON CONFLICT(chat_id) DO UPDATE SET active=1, timer_duration=excluded.timer_duration,
               allowed_stars=excluded.allowed_stars, description=excluded.description,
               current_leader_id=NULL, leader_name=NULL, timer_start=NULL, job_name=NULL,
               bid_count=0, total_stars=0""",
            (chat_id, timer, stars_json, description)
        )
        await self._db.commit()

    async def update_game_settings(self, chat_id, timer=None, stars=None):
        if timer is not None:
            await self._db.execute("UPDATE games SET timer_duration=? WHERE chat_id=? AND active=1", (timer, chat_id))
        if stars is not None:
            stars_json = json.dumps(stars)
            await self._db.execute("UPDATE games SET allowed_stars=? WHERE chat_id=? AND active=1", (stars_json, chat_id))
        await self._db.commit()

    async def update_leader(self, chat_id, user_id, user_name, timer_start, job_name):
        await self._db.execute(
            "UPDATE games SET current_leader_id=?, leader_name=?, timer_start=?, job_name=? WHERE chat_id=? AND active=1",
            (user_id, user_name, timer_start, job_name, chat_id)
        )
        await self._db.commit()

    async def increment_bid(self, chat_id, stars: int = 0):
        await self._db.execute(
            "UPDATE games SET bid_count = bid_count + 1, total_stars = total_stars + ? WHERE chat_id=? AND active=1",
            (stars, chat_id)
        )
        await self._db.commit()

    async def deactivate_game(self, chat_id):
        await self._db.execute(
            "INSERT INTO auction_history (chat_id, winner_id, winner_name, description, total_bids, total_stars) SELECT chat_id, current_leader_id, leader_name, description, bid_count, total_stars FROM games WHERE chat_id=? AND active=1",
            (chat_id,)
        )
        await self._db.execute(
            "UPDATE games SET active=0, current_leader_id=NULL, leader_name=NULL, timer_start=NULL, job_name=NULL WHERE chat_id=?",
            (chat_id,)
        )
        await self._db.commit()

    async def get_active_game(self, chat_id) -> Optional[Dict[str, Any]]:
        cur = await self._db.execute("SELECT * FROM games WHERE chat_id=? AND active=1", (chat_id,))
        row = await cur.fetchone()
        if not row: return None
        game = dict(row)
        game["allowed_stars"] = json.loads(game["allowed_stars"])
        return game

    async def get_all_active_games(self) -> List[Dict[str, Any]]:
        cur = await self._db.execute("SELECT * FROM games WHERE active=1")
        rows = await cur.fetchall()
        games = []
        for row in rows:
            g = dict(row)
            g["allowed_stars"] = json.loads(g["allowed_stars"])
            games.append(g)
        return games

    async def get_active_game_counts(self) -> Dict[str, int]:
        """Fast count query for status."""
        cur = await self._db.execute("SELECT COUNT(*) as c FROM games WHERE active=1")
        row = await cur.fetchone()
        auc = row['c'] if row else 0
        cur = await self._db.execute("SELECT COUNT(*) as c FROM lucky_draws WHERE active=1")
        row = await cur.fetchone()
        lucky = row['c'] if row else 0
        cur = await self._db.execute("SELECT COUNT(*) as c FROM dice_games WHERE active=1")
        row = await cur.fetchone()
        dice = row['c'] if row else 0
        return {'auctions': auc, 'lucky_draws': lucky, 'dice': dice}

    async def create_lucky_draw(self, chat_id, chance, prize, photo_file_id=None):
        await self._db.execute(
            "INSERT INTO lucky_draws (chat_id, active, chance, prize, photo_file_id) VALUES (?,1,?,?,?) ON CONFLICT(chat_id) DO UPDATE SET active=1, chance=excluded.chance, prize=excluded.prize, photo_file_id=excluded.photo_file_id",
            (chat_id, chance, prize, photo_file_id)
        )
        await self._db.commit()

    async def get_active_lucky_draw(self, chat_id) -> Optional[Dict[str, Any]]:
        cur = await self._db.execute("SELECT * FROM lucky_draws WHERE chat_id=? AND active=1", (chat_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def deactivate_lucky_draw(self, chat_id):
        await self._db.execute("UPDATE lucky_draws SET active=0 WHERE chat_id=?", (chat_id,))
        await self._db.commit()

    async def get_all_active_lucky_draws(self) -> List[Dict[str, Any]]:
        cur = await self._db.execute("SELECT * FROM lucky_draws WHERE active=1")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def create_dice_game(self, chat_id, dice_emoji, winning_value, prize):
        await self._db.execute(
            "INSERT INTO dice_games (chat_id, active, dice_emoji, winning_value, prize) VALUES (?,1,?,?,?) ON CONFLICT(chat_id) DO UPDATE SET active=1, dice_emoji=excluded.dice_emoji, winning_value=excluded.winning_value, prize=excluded.prize",
            (chat_id, dice_emoji, winning_value, prize)
        )
        await self._db.commit()

    async def get_active_dice_game(self, chat_id) -> Optional[Dict[str, Any]]:
        cur = await self._db.execute("SELECT * FROM dice_games WHERE chat_id=? AND active=1", (chat_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def deactivate_dice_game(self, chat_id):
        await self._db.execute("UPDATE dice_games SET active=0 WHERE chat_id=?", (chat_id,))
        await self._db.commit()

    async def get_all_active_dice_games(self) -> List[Dict[str, Any]]:
        cur = await self._db.execute("SELECT * FROM dice_games WHERE active=1")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def close(self):
        if self._db: await self._db.close()