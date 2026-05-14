#!/usr/bin/env python3
import asyncio, logging, sys
from pathlib import Path
from telegram.ext import ApplicationBuilder, ContextTypes
from config import Config
from database import Database
from auction import AuctionManager
from handlers.admin_private import register_admin_handlers
from handlers.group_messages import register_group_handlers

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

def setup_dirs():
    Path("data").mkdir(exist_ok=True)
    Path("logs").mkdir(exist_ok=True)

class App:
    def __init__(self):
        self.application = None
        self.db = Database()
        self.auction_mgr = AuctionManager()
        self._heartbeat_job = None

    async def initialize(self):
        Config.validate()
        setup_dirs()
        await self.db.initialize()
        self.application = ApplicationBuilder().token(Config.BOT_TOKEN).concurrent_updates(True).build()
        register_admin_handlers(self.application)
        register_group_handlers(self.application)
        await self.auction_mgr.restore_timers(self.application)
        logger.info("Bot initialized")

    async def start(self):
        try:
            logger.info("Starting polling...")
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query", "my_chat_member"]
            )
            # Periodic heartbeat every 60 seconds
            self._heartbeat_job = self.application.job_queue.run_repeating(
                self._admin_heartbeat, interval=3600, first=10
            )
            logger.info("Heartbeat job started")
            await asyncio.Future()
        except KeyboardInterrupt:
            pass
        finally:
            await self.shutdown()

    async def shutdown(self):
        if self._heartbeat_job:
            self._heartbeat_job.schedule_removal()
        if self.application:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
        await self.db.close()
        logger.info("Bot shut down completely")

    async def _admin_heartbeat(self, context: ContextTypes.DEFAULT_TYPE):
        """Send minimal bot status to all admins."""
        try:
            counts = await self.db.get_active_game_counts()
            auctions = counts['auctions']
            lucky = counts['lucky_draws']
            dice = counts['dice']
            total = auctions + lucky + dice
            if total == 0:
                msg = "✅ Бот активен. Сейчас нет активных игр."
            else:
                parts = []
                if auctions: parts.append(f"Аукционы: {auctions}")
                if lucky: parts.append(f"Lucky Draw: {lucky}")
                if dice: parts.append(f"Кости: {dice}")
                msg = f"✅ Бот активен. Активных игр: {total} ({', '.join(parts)})"
            for admin_id in Config.ADMIN_IDS:
                try:
                    await context.bot.send_message(admin_id, msg)
                except Exception:
                    logger.debug(f"Could not send heartbeat to admin {admin_id}")
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")

async def main():
    app = App()
    await app.initialize()
    await app.start()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)