"""Admin private chat handlers – with Lucky Draw editing, fixed ignore."""
from telegram import Update
from telegram.ext import (
    CommandHandler, CallbackQueryHandler, ConversationHandler,
    MessageHandler, filters, ContextTypes
)
from config import Config
from database import Database
from keyboards import *
from lucky_draw import LuckyDrawManager
from guess_number import GuessNumberManager
import logging, html, random, time

logger = logging.getLogger(__name__)

# States
ASK_TIMER, ASK_STARS, ASK_DESCRIPTION = range(3)
ASK_CHANCE, ASK_PRIZE, ASK_PHOTO, ASK_WINNERS, ASK_LUCKY_DURATION, ASK_GIFT_ID = range(10, 16)
DICE_EMOJI, DICE_VALUE, DICE_PRIZE = range(20, 23)
EDIT_TIMER, EDIT_STARS = range(30, 32)
GUESS_MIN, GUESS_MAX, GUESS_DURATION, GUESS_PRIZE, GUESS_PHOTO = range(40, 45)
# Edit lucky draw states
EDIT_LUCKY_CHANCE, EDIT_LUCKY_WINNERS, EDIT_LUCKY_DURATION, EDIT_LUCKY_PRIZE, EDIT_LUCKY_PHOTO, EDIT_LUCKY_GIFT = range(50, 56)

db = Database()
lucky_mgr = LuckyDrawManager()
guess_mgr = GuessNumberManager()

async def is_admin(uid): return uid in Config.ADMIN_IDS

# ── /status (public) ──
async def status_public(update: Update, context: ContextTypes.DEFAULT_TYPE):
    counts = await db.get_active_game_counts()
    parts = []
    if counts['auctions']: parts.append(f"Аукционы: {counts['auctions']}")
    if counts['lucky_draws']: parts.append(f"Lucky Draw: {counts['lucky_draws']}")
    if counts['dice']: parts.append(f"Кости: {counts['dice']}")
    if counts['guess_number']: parts.append(f"Угадай число: {counts['guess_number']}")
    if parts:
        text = "📊 <b>Статус бота:</b>\n" + "\n".join(parts)
    else:
        text = "📊 <b>Статус бота:</b> нет активных игр."
    await update.message.reply_text(text, parse_mode="HTML")

# ── /start, /active, /stop, /stats (admin only) ──
async def start_cmd(update: Update, context):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Нет доступа.")
        return
    groups = await db.get_all_groups()
    if not groups:
        await update.message.reply_text("📭 Бот не добавлен в группы.")
        return
    await update.message.reply_text("🎮 Выберите группу:", reply_markup=build_group_selection_keyboard(groups))

async def active_cmd(update: Update, context):
    if not await is_admin(update.effective_user.id): return
    games = await db.get_all_active_games()
    draws = await db.get_all_active_lucky_draws()
    dice = await db.get_all_active_dice_games()
    guess = await db.get_all_active_guess_numbers()
    if not (games or draws or dice or guess):
        await update.message.reply_text("Нет активных игр.")
        return
    await update.message.reply_text("🏃 Активные игры:", reply_markup=build_active_games_keyboard(games, draws, dice, guess), parse_mode="HTML")

async def stop_cmd(update: Update, context):
    await active_cmd(update, context)

async def stats_cmd(update: Update, context):
    if not await is_admin(update.effective_user.id): return
    games = await db.get_all_active_games()
    if not games: await update.message.reply_text("Нет активных аукционов."); return
    text = "📊 <b>Статистика аукционов:</b>\n"
    for g in games:
        leader = g.get('leader_name', 'Нет')
        bids = g.get('bid_count',0)
        stars = g.get('total_stars',0)
        text += f"\nГруппа <code>{g['chat_id']}</code>: лидер {leader}, ставок: {bids}, звёзд: {stars}"
    await update.message.reply_text(text, parse_mode="HTML")

# ── group select -> mode ──
async def select_group_cb(update: Update, context):
    query = update.callback_query; await query.answer()
    if not await is_admin(update.effective_user.id): return await query.edit_message_text("⛔ Нет доступа.")
    chat_id = int(query.data.split(":")[1])
    context.user_data["selected_chat_id"] = chat_id
    await query.edit_message_text(f"📱 Группа <code>{chat_id}</code>\nВыберите режим:", reply_markup=build_game_mode_keyboard(chat_id), parse_mode="HTML")

# ── Auction ── (unchanged, same as before)
# ... (I'll include the auction functions to keep the file complete)
async def auction_mode_cb(update: Update, context):
    query = update.callback_query; await query.answer()
    chat_id = int(query.data.split(":")[1])
    context.user_data["auction_chat_id"] = chat_id
    await query.edit_message_text("💰 Ивент (аукцион)\nВыберите настройки:", reply_markup=build_auction_options_keyboard(chat_id))

async def auction_default_cb(update: Update, context):
    query = update.callback_query; await query.answer()
    chat_id = int(query.data.split(":")[1])
    await db.create_active_game(chat_id, Config.DEFAULT_TIMER, Config.DEFAULT_STARS)
    game = await db.get_active_game(chat_id)
    stars = ', '.join(map(str, game['allowed_stars']))
    mins = game['timer_duration'] // 60
    prize = html.escape(game.get('description', '🎁'))
    desc_line = f"🎁 Приз: {prize}\n" if prize else ""
    try:
        await context.bot.send_message(chat_id, f"🎉 <b>Ивент начался!</b>\n\n⭐ 1 сообщение в чате = {stars} звёзд.\n⏱ Цель: продержаться {mins} мин без перебива.\n{desc_line}", parse_mode="HTML")
    except Exception as e: logger.error(f"Announce fail: {e}")
    await query.edit_message_text("✅ Ивент запущен со стандартными настройками.")

async def auction_custom_cb(update: Update, context) -> int:
    query = update.callback_query; await query.answer()
    chat_id = int(query.data.split(":")[1])
    context.user_data["custom_chat_id"] = chat_id
    await query.edit_message_text(f"⏱ Введите длительность в секундах ({Config.MIN_TIMER}-{Config.MAX_TIMER}):")
    return ASK_TIMER

async def ask_timer(update: Update, context) -> int:
    text = update.message.text.strip()
    if not text.isdigit() or not (Config.MIN_TIMER <= int(text) <= Config.MAX_TIMER):
        await update.message.reply_text(f"❌ Введите число от {Config.MIN_TIMER} до {Config.MAX_TIMER}:")
        return ASK_TIMER
    context.user_data["custom_timer"] = int(text)
    await update.message.reply_text("💎 Введите разрешённые звёзды через запятую (например, 1,2,5):")
    return ASK_STARS

async def ask_stars(update: Update, context) -> int:
    text = update.message.text.strip()
    try:
        stars = [int(s.strip()) for s in text.split(",") if s.strip()]
        if not stars or any(not (1 <= s <= 999) for s in stars): raise ValueError
        stars = sorted(set(stars))
    except:
        await update.message.reply_text("❌ Введите положительные числа: 1,2,3")
        return ASK_STARS
    context.user_data["custom_stars"] = stars
    await update.message.reply_text("🎁 Описание приза (или /skip):")
    return ASK_DESCRIPTION

async def ask_description(update: Update, context) -> int:
    text = update.message.text.strip()
    description = "" if text.lower() == "/skip" else text
    chat_id = context.user_data["custom_chat_id"]
    timer = context.user_data["custom_timer"]
    stars = context.user_data["custom_stars"]
    await db.create_active_game(chat_id, timer, stars, description)
    await update.message.reply_text(f"✅ Ивент создан в группе {chat_id}!")
    mins = timer // 60
    prize = html.escape(description) if description else '🎁'
    desc_line = f"🎁 Приз: {prize}\n" if description else ""
    try:
        await context.bot.send_message(chat_id, f"🎉 <b>Ивент начался!</b>\n\n⭐ 1 сообщение в чате = {', '.join(map(str, stars))} звёзд.\n⏱ Цель: продержаться {mins} мин без перебива.\n{desc_line}", parse_mode="HTML")
    except Exception as e: logger.error(f"Announce fail: {e}")
    return ConversationHandler.END

# ── Edit auction ──
async def edit_game_cb(update: Update, context):
    query = update.callback_query; await query.answer()
    if not await is_admin(update.effective_user.id): return
    chat_id = int(query.data.split(":")[1])
    context.user_data["edit_chat_id"] = chat_id
    await query.edit_message_text(f"✏️ Изменить аукцион в группе <code>{chat_id}</code>", reply_markup=build_edit_game_keyboard(chat_id), parse_mode="HTML")

async def edit_timer_cb(update: Update, context) -> int:
    query = update.callback_query; await query.answer()
    chat_id = int(query.data.split(":")[1])
    context.user_data["edit_chat_id"] = chat_id
    await query.edit_message_text(f"⏱ Введите новую длительность в секундах ({Config.MIN_TIMER}-{Config.MAX_TIMER}):")
    return EDIT_TIMER

async def edit_stars_cb(update: Update, context) -> int:
    query = update.callback_query; await query.answer()
    chat_id = int(query.data.split(":")[1])
    context.user_data["edit_chat_id"] = chat_id
    await query.edit_message_text("💎 Введите новые разрешённые звёзды через запятую (например, 1,2,5):")
    return EDIT_STARS

async def edit_timer_value(update: Update, context):
    text = update.message.text.strip()
    if not text.isdigit() or not (Config.MIN_TIMER <= int(text) <= Config.MAX_TIMER):
        await update.message.reply_text(f"❌ Введите число от {Config.MIN_TIMER} до {Config.MAX_TIMER}:")
        return EDIT_TIMER
    new_timer = int(text)
    chat_id = context.user_data["edit_chat_id"]
    await db.update_game_settings(chat_id, timer=new_timer)
    mins = new_timer // 60; secs = new_timer % 60
    duration_str = f"{mins} мин" if secs == 0 else f"{mins} мин {secs} сек"
    try: await context.bot.send_message(chat_id, f"⏱ <b>Время изменено!</b> Новая длительность: {duration_str}.", parse_mode="HTML")
    except: pass
    await update.message.reply_text(f"✅ Время изменено на {new_timer} сек.")
    return ConversationHandler.END

async def edit_stars_value(update: Update, context):
    text = update.message.text.strip()
    try:
        stars = [int(s.strip()) for s in text.split(",") if s.strip()]
        if not stars or any(not (1 <= s <= 999) for s in stars): raise ValueError
        stars = sorted(set(stars))
    except:
        await update.message.reply_text("❌ Введите положительные числа: 1,2,3"); return EDIT_STARS
    chat_id = context.user_data["edit_chat_id"]
    await db.update_game_settings(chat_id, stars=stars)
    await update.message.reply_text(f"✅ Звёзды изменены на {', '.join(map(str, stars))}.")
    return ConversationHandler.END

# ── Lucky Draw (creation) ── (unchanged)
async def lucky_draw_cb(update: Update, context) -> int:
    query = update.callback_query; await query.answer()
    chat_id = int(query.data.split(":")[1])
    context.user_data["draw_chat_id"] = chat_id
    await query.edit_message_text("🎰 Введите шанс выигрыша (0.001 – 100)%:")
    return ASK_CHANCE

async def ask_chance(update: Update, context) -> int:
    text = update.message.text.strip().replace(',', '.')
    try:
        chance = float(text)
        if not (0.001 <= chance <= 100): raise ValueError
    except:
        await update.message.reply_text("❌ Введите число от 0.001 до 100."); return ASK_CHANCE
    context.user_data["draw_chance"] = chance
    await update.message.reply_text("🎁 Введите описание приза:"); return ASK_PRIZE

async def ask_prize(update: Update, context) -> int:
    prize = update.message.text.strip()
    if not prize: await update.message.reply_text("❌ Приз не может быть пустым."); return ASK_PRIZE
    context.user_data["draw_prize"] = prize
    await update.message.reply_text("👥 Введите количество победителей (по умолчанию 1):"); return ASK_WINNERS

async def ask_winners(update: Update, context) -> int:
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1: await update.message.reply_text("❌ Введите целое число больше 0."); return ASK_WINNERS
    context.user_data["draw_winners"] = int(text)
    await update.message.reply_text("⏱ Введите длительность игры в минутах (0 = без ограничения):"); return ASK_LUCKY_DURATION

async def ask_lucky_duration(update: Update, context) -> int:
    text = update.message.text.strip()
    if not text.isdigit(): await update.message.reply_text("❌ Введите число минут."); return ASK_LUCKY_DURATION
    context.user_data["draw_duration"] = int(text)
    await update.message.reply_text("🖼 Отправьте фото для объявления (или /skip):"); return ASK_PHOTO

async def ask_photo(update: Update, context) -> int:
    if update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
        context.user_data["draw_photo"] = photo_file_id
        await update.message.reply_text("✅ Фото получено.")
    elif update.message.text and update.message.text.lower() == "/skip":
        context.user_data["draw_photo"] = None
    else:
        await update.message.reply_text("❌ Отправьте фото или /skip."); return ASK_PHOTO
    await update.message.reply_text("🎁 Введите gift_id подарка (числовой ID) или /skip:"); return ASK_GIFT_ID

async def ask_gift_id(update: Update, context) -> int:
    text = update.message.text.strip()
    gift_id = None if text.lower() == "/skip" else text
    chat_id = context.user_data["draw_chat_id"]
    chance = context.user_data["draw_chance"]
    prize = context.user_data["draw_prize"]
    winners = context.user_data["draw_winners"]
    duration = context.user_data["draw_duration"]
    photo_file_id = context.user_data.get("draw_photo")
    await db.create_lucky_draw(chat_id, chance, prize, photo_file_id, gift_id, winners, duration)
    await update.message.reply_text(f"✅ Lucky Draw активирован в {chat_id}!")
    if duration > 0:
        now = time.time()
        job_name = f"lucky_end_{chat_id}_{int(now)}"
        context.application.job_queue.run_once(
            lambda ctx, cid=chat_id: lucky_mgr._end_lucky_draw(ctx, cid, "Время вышло"),
            duration * 60, chat_id=chat_id, name=job_name
        )
        await db.set_lucky_draw_timer(chat_id, now, job_name)
    caption = f"🎰 <b>Lucky Draw!</b>\n🎁 Приз: {html.escape(prize)}\n🎲 Шанс: {chance}%\n👥 Победителей: {winners}"
    if duration > 0: caption += f"\n⏱ Длительность: {duration} мин"
    try:
        if photo_file_id: await context.bot.send_photo(chat_id, photo_file_id, caption=caption, parse_mode="HTML")
        else: await context.bot.send_message(chat_id, caption, parse_mode="HTML")
    except Exception as e: logger.error(f"Announce fail: {e}")
    return ConversationHandler.END

# ── Edit Lucky Draw (new) ──
async def edit_lucky_cb(update: Update, context):
    query = update.callback_query; await query.answer()
    if not await is_admin(update.effective_user.id): return
    chat_id = int(query.data.split(":")[1])
    context.user_data["edit_lucky_chat_id"] = chat_id
    await query.edit_message_text("✏️ Выберите, что изменить в Lucky Draw:", reply_markup=build_edit_lucky_keyboard(chat_id))

# Individual edit entry points (all return a state)
async def edit_lucky_chance_cb(update: Update, context) -> int:
    query = update.callback_query; await query.answer()
    chat_id = int(query.data.split(":")[1])
    context.user_data["edit_lucky_chat_id"] = chat_id
    await query.edit_message_text("🎲 Введите новый шанс (0.001 – 100)%:")
    return EDIT_LUCKY_CHANCE

async def edit_lucky_winners_cb(update: Update, context) -> int:
    query = update.callback_query; await query.answer()
    chat_id = int(query.data.split(":")[1])
    context.user_data["edit_lucky_chat_id"] = chat_id
    await query.edit_message_text("👥 Введите новое количество победителей:")
    return EDIT_LUCKY_WINNERS

async def edit_lucky_duration_cb(update: Update, context) -> int:
    query = update.callback_query; await query.answer()
    chat_id = int(query.data.split(":")[1])
    context.user_data["edit_lucky_chat_id"] = chat_id
    await query.edit_message_text("⏱ Введите новую длительность в минутах (0 = без ограничения):")
    return EDIT_LUCKY_DURATION

async def edit_lucky_prize_cb(update: Update, context) -> int:
    query = update.callback_query; await query.answer()
    chat_id = int(query.data.split(":")[1])
    context.user_data["edit_lucky_chat_id"] = chat_id
    await query.edit_message_text("🎁 Введите новое описание приза:")
    return EDIT_LUCKY_PRIZE

async def edit_lucky_photo_cb(update: Update, context) -> int:
    query = update.callback_query; await query.answer()
    chat_id = int(query.data.split(":")[1])
    context.user_data["edit_lucky_chat_id"] = chat_id
    await query.edit_message_text("🖼 Отправьте новое фото (или /skip для удаления):")
    return EDIT_LUCKY_PHOTO

async def edit_lucky_gift_cb(update: Update, context) -> int:
    query = update.callback_query; await query.answer()
    chat_id = int(query.data.split(":")[1])
    context.user_data["edit_lucky_chat_id"] = chat_id
    await query.edit_message_text("🎁 Введите новый gift_id (числовой) или /skip для удаления:")
    return EDIT_LUCKY_GIFT

# Handlers for new values
async def edit_lucky_chance_value(update: Update, context):
    text = update.message.text.strip().replace(',', '.')
    try:
        chance = float(text)
        if not (0.001 <= chance <= 100): raise ValueError
    except:
        await update.message.reply_text("❌ Введите число от 0.001 до 100."); return EDIT_LUCKY_CHANCE
    chat_id = context.user_data["edit_lucky_chat_id"]
    await db.update_lucky_draw_settings(chat_id, chance=chance)
    await update.message.reply_text(f"✅ Шанс изменён на {chance}%.")
    return ConversationHandler.END

async def edit_lucky_winners_value(update: Update, context):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("❌ Введите целое число больше 0."); return EDIT_LUCKY_WINNERS
    winners = int(text)
    chat_id = context.user_data["edit_lucky_chat_id"]
    await db.update_lucky_draw_settings(chat_id, winners_count=winners)
    # Also reset winner_ids list if we increase count? Better to keep existing winners but allow new ones.
    # We'll just update the count; existing winner_ids remain, meaning more slots are now open.
    await update.message.reply_text(f"✅ Количество победителей изменено на {winners}.")
    return ConversationHandler.END

async def edit_lucky_duration_value(update: Update, context):
    text = update.message.text.strip()
    if not text.isdigit(): await update.message.reply_text("❌ Введите число минут."); return EDIT_LUCKY_DURATION
    duration = int(text)
    chat_id = context.user_data["edit_lucky_chat_id"]
    await db.update_lucky_draw_settings(chat_id, duration_minutes=duration)
    # Cancel old timer job if any
    game = await db.get_active_lucky_draw(chat_id)
    if game and game.get('job_name'):
        for j in context.job_queue.jobs():
            if j.name == game['job_name']: j.schedule_removal()
    if duration > 0:
        now = time.time()
        job_name = f"lucky_end_{chat_id}_{int(now)}"
        context.application.job_queue.run_once(
            lambda ctx, cid=chat_id: lucky_mgr._end_lucky_draw(ctx, cid, "Время вышло"),
            duration * 60, chat_id=chat_id, name=job_name
        )
        await db.set_lucky_draw_timer(chat_id, now, job_name)
    else:
        # Timer removed
        await db.set_lucky_draw_timer(chat_id, None, None)
    await update.message.reply_text(f"✅ Длительность изменена на {duration} мин.")
    return ConversationHandler.END

async def edit_lucky_prize_value(update: Update, context):
    prize = update.message.text.strip()
    if not prize: await update.message.reply_text("❌ Приз не может быть пустым."); return EDIT_LUCKY_PRIZE
    chat_id = context.user_data["edit_lucky_chat_id"]
    await db.update_lucky_draw_settings(chat_id, prize=prize)
    await update.message.reply_text("✅ Приз обновлён.")
    return ConversationHandler.END

async def edit_lucky_photo_value(update: Update, context):
    chat_id = context.user_data["edit_lucky_chat_id"]
    if update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
        await db.update_lucky_draw_settings(chat_id, photo_file_id=photo_file_id)
        await update.message.reply_text("✅ Фото обновлено.")
    elif update.message.text and update.message.text.lower() == "/skip":
        await db.update_lucky_draw_settings(chat_id, photo_file_id=None)
        await update.message.reply_text("✅ Фото удалено.")
    else:
        await update.message.reply_text("❌ Отправьте фото или /skip."); return EDIT_LUCKY_PHOTO
    return ConversationHandler.END

async def edit_lucky_gift_value(update: Update, context):
    chat_id = context.user_data["edit_lucky_chat_id"]
    text = update.message.text.strip()
    gift_id = None if text.lower() == "/skip" else text
    await db.update_lucky_draw_settings(chat_id, gift_id=gift_id)
    await update.message.reply_text("✅ Подарок обновлён.")
    return ConversationHandler.END

# ── Guess Number ── (unchanged)
async def guess_mode_cb(update: Update, context) -> int:
    query = update.callback_query; await query.answer()
    chat_id = int(query.data.split(":")[1])
    context.user_data["guess_chat_id"] = chat_id
    await query.edit_message_text("🎯 Введите минимальное число:"); return GUESS_MIN

async def guess_min(update: Update, context) -> int:
    text = update.message.text.strip()
    if not text.isdigit(): await update.message.reply_text("❌ Введите число."); return GUESS_MIN
    context.user_data["guess_min"] = int(text)
    await update.message.reply_text("🎯 Введите максимальное число:"); return GUESS_MAX

async def guess_max(update: Update, context) -> int:
    text = update.message.text.strip()
    if not text.isdigit() or int(text) <= context.user_data["guess_min"]:
        await update.message.reply_text("❌ Число должно быть больше минимального."); return GUESS_MAX
    context.user_data["guess_max"] = int(text)
    await update.message.reply_text("⏱ Введите длительность игры в минутах (0 = без ограничения):"); return GUESS_DURATION

async def guess_duration(update: Update, context) -> int:
    text = update.message.text.strip()
    if not text.isdigit(): await update.message.reply_text("❌ Введите число минут."); return GUESS_DURATION
    context.user_data["guess_duration"] = int(text)
    await update.message.reply_text("🎁 Введите описание приза:"); return GUESS_PRIZE

async def guess_prize(update: Update, context) -> int:
    prize = update.message.text.strip()
    if not prize: await update.message.reply_text("❌ Приз не может быть пустым."); return GUESS_PRIZE
    context.user_data["guess_prize"] = prize
    await update.message.reply_text("🖼 Отправьте фото для объявления (или /skip):"); return GUESS_PHOTO

async def guess_photo(update: Update, context) -> int:
    if update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
        context.user_data["guess_photo"] = photo_file_id
        await update.message.reply_text("✅ Фото получено.")
    elif update.message.text and update.message.text.lower() == "/skip":
        context.user_data["guess_photo"] = None
    else:
        await update.message.reply_text("❌ Отправьте фото или /skip."); return GUESS_PHOTO
    chat_id = context.user_data["guess_chat_id"]
    min_num = context.user_data["guess_min"]
    max_num = context.user_data["guess_max"]
    duration = context.user_data["guess_duration"]
    prize = context.user_data["guess_prize"]
    secret = random.randint(min_num, max_num)
    photo_file_id = context.user_data.get("guess_photo")
    await db.create_guess_number(chat_id, min_num, max_num, secret, prize, duration, photo_file_id)
    await update.message.reply_text(f"✅ Игра «Угадай число» создана в {chat_id}!\nЗагаданное число: <b>{secret}</b>", parse_mode="HTML")
    for admin_id in Config.ADMIN_IDS:
        try: await context.bot.send_message(admin_id, f"🔐 Загаданное число в группе <code>{chat_id}</code>: <b>{secret}</b>", parse_mode="HTML")
        except: pass
    if duration > 0:
        now = time.time()
        job_name = f"guess_end_{chat_id}_{int(now)}"
        context.application.job_queue.run_once(
            lambda ctx, cid=chat_id: guess_mgr._end_guess_game(ctx, cid),
            duration * 60, chat_id=chat_id, name=job_name
        )
        await db.set_guess_number_timer(chat_id, now, job_name)
    caption = f"🎯 <b>Угадай число!</b>\nДиапазон: {min_num}–{max_num}\n🎁 Приз: {html.escape(prize)}"
    if duration > 0: caption += f"\n⏱ Время: {duration} мин"
    try:
        if photo_file_id: await context.bot.send_photo(chat_id, photo_file_id, caption=caption, parse_mode="HTML")
        else: await context.bot.send_message(chat_id, caption, parse_mode="HTML")
    except Exception as e: logger.error(f"Announce fail: {e}")
    return ConversationHandler.END

# ── Dice Game ── (unchanged)
async def dice_mode_cb(update: Update, context) -> int:
    query = update.callback_query; await query.answer()
    chat_id = int(query.data.split(":")[1])
    context.user_data["dice_chat_id"] = chat_id
    await query.edit_message_text("🎲 Выберите кость/игру:", reply_markup=build_dice_emoji_keyboard())
    return DICE_EMOJI

async def dice_emoji_chosen(update: Update, context):
    query = update.callback_query; await query.answer()
    emoji = query.data.split("_", 2)[2]
    context.user_data["dice_emoji"] = emoji
    if emoji == "🎰": max_val = 64; hint = " (64 = 777)"
    elif emoji in ("🎲","🎯"): max_val = 6; hint = ""
    else: max_val = 5; hint = ""
    await query.edit_message_text(f"🎯 Введите выигрышное значение (от 1 до {max_val}){hint}:")
    return DICE_VALUE

async def dice_value_entered(update: Update, context) -> int:
    text = update.message.text.strip()
    emoji = context.user_data["dice_emoji"]
    if emoji == "🎰": max_val = 64
    elif emoji in ("🎲","🎯"): max_val = 6
    else: max_val = 5
    if not text.isdigit() or not (1 <= int(text) <= max_val):
        await update.message.reply_text(f"❌ Введите число от 1 до {max_val}:"); return DICE_VALUE
    context.user_data["dice_value"] = int(text)
    await update.message.reply_text("🎁 Введите описание приза:"); return DICE_PRIZE

async def dice_prize_entered(update: Update, context) -> int:
    prize = update.message.text.strip()
    if not prize: await update.message.reply_text("❌ Приз не может быть пустым."); return DICE_PRIZE
    chat_id = context.user_data["dice_chat_id"]
    emoji = context.user_data["dice_emoji"]
    value = context.user_data["dice_value"]
    await db.create_dice_game(chat_id, emoji, value, prize)
    await update.message.reply_text(f"✅ Игра с {emoji} на {value} создана в группе {chat_id}!")
    try: await context.bot.send_message(chat_id, f"🎲 <b>Игра начата!</b> Отправьте {emoji}, чтобы попробовать выбить {value} и выиграть: {html.escape(prize)}.", parse_mode="HTML")
    except: pass
    return ConversationHandler.END

# ── Stop handlers ──
async def stop_game_cb(update: Update, context):
    query = update.callback_query; await query.answer()
    if not await is_admin(update.effective_user.id): return
    chat_id = int(query.data.split(":")[1])
    for j in context.job_queue.jobs():
        if j.name and (j.name.startswith(f"auction_{chat_id}") or j.name.startswith(f"countdown_{chat_id}")): j.schedule_removal()
    await db.deactivate_game(chat_id)
    await query.edit_message_text(f"🛑 Ивент остановлен в {chat_id}.")
    try: await context.bot.send_message(chat_id, "🛑 Ивент остановлен администратором.")
    except: pass

async def stop_lucky_cb(update: Update, context):
    query = update.callback_query; await query.answer()
    if not await is_admin(update.effective_user.id): return
    chat_id = int(query.data.split(":")[1])
    game = await db.get_active_lucky_draw(chat_id)
    if game and game.get('job_name'):
        for j in context.job_queue.jobs():
            if j.name == game['job_name']: j.schedule_removal()
    await db.deactivate_lucky_draw(chat_id)
    await query.edit_message_text(f"🎰 Lucky Draw остановлен в {chat_id}.")
    try: await context.bot.send_message(chat_id, "🎰 Lucky Draw остановлен администратором.")
    except: pass

async def stop_dice_cb(update: Update, context):
    query = update.callback_query; await query.answer()
    if not await is_admin(update.effective_user.id): return
    chat_id = int(query.data.split(":")[1])
    await db.deactivate_dice_game(chat_id)
    await query.edit_message_text(f"🎲 Dice Game остановлена в {chat_id}.")
    try: await context.bot.send_message(chat_id, "🎲 Игра остановлена администратором.")
    except: pass

async def stop_guess_cb(update: Update, context):
    query = update.callback_query; await query.answer()
    if not await is_admin(update.effective_user.id): return
    chat_id = int(query.data.split(":")[1])
    await guess_mgr._end_guess_game(context, chat_id)
    await query.edit_message_text(f"🎯 Guess Number остановлена в {chat_id}.")
    try: await context.bot.send_message(chat_id, "🎯 Игра остановлена администратором.")
    except: pass

async def stats_game_cb(update: Update, context):
    query = update.callback_query; await query.answer()
    chat_id = int(query.data.split(":")[1])
    game = await db.get_active_game(chat_id)
    if not game: await query.edit_message_text("Аукцион не активен."); return
    await query.edit_message_text(f"📊 <b>Статистика аукциона в {chat_id}</b>\nЛидер: {game.get('leader_name','Нет')}\nСтавок: {game.get('bid_count',0)}\nЗвёзд: {game.get('total_stars',0)}", parse_mode="HTML")

async def back_to_mode_cb(update: Update, context):
    query = update.callback_query; await query.answer()
    chat_id = int(query.data.split(":")[1])
    await query.edit_message_text("Выберите режим:", reply_markup=build_game_mode_keyboard(chat_id))

async def back_from_edit_cb(update: Update, context):
    query = update.callback_query; await query.answer()
    await active_cmd(update, context)

async def cancel_cb(update: Update, context):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("❌ Отменено.")

async def cancel_conv(update: Update, context) -> int:
    await update.message.reply_text("❌ Настройка отменена.")
    return ConversationHandler.END

def register_admin_handlers(app):
    # Conversations
    auction_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(auction_custom_cb, pattern=r"^auction_custom:")],
        states={
            ASK_TIMER: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_timer)],
            ASK_STARS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_stars)],
            ASK_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_description),
                              CommandHandler("skip", lambda u, c: ask_description(u, c))]
        },
        fallbacks=[CommandHandler("cancel", cancel_conv), CommandHandler("start", cancel_conv)],
        per_user=True
    )
    lucky_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(lucky_draw_cb, pattern=r"^lucky_draw_mode:")],
        states={
            ASK_CHANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_chance)],
            ASK_PRIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_prize)],
            ASK_WINNERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_winners)],
            ASK_LUCKY_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_lucky_duration)],
            ASK_PHOTO: [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), ask_photo),
                        CommandHandler("skip", lambda u, c: ask_photo(u, c))],
            ASK_GIFT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_gift_id),
                          CommandHandler("skip", lambda u, c: ask_gift_id(u, c))]
        },
        fallbacks=[CommandHandler("cancel", cancel_conv), CommandHandler("start", cancel_conv)],
        per_user=True
    )
    dice_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(dice_mode_cb, pattern=r"^dice_mode:")],
        states={
            DICE_EMOJI: [CallbackQueryHandler(dice_emoji_chosen, pattern=r"^dice_emoji_")],
            DICE_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, dice_value_entered)],
            DICE_PRIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, dice_prize_entered)]
        },
        fallbacks=[CommandHandler("cancel", cancel_conv), CommandHandler("start", cancel_conv)],
        per_user=True
    )
    guess_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(guess_mode_cb, pattern=r"^guess_mode:")],
        states={
            GUESS_MIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, guess_min)],
            GUESS_MAX: [MessageHandler(filters.TEXT & ~filters.COMMAND, guess_max)],
            GUESS_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, guess_duration)],
            GUESS_PRIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, guess_prize)],
            GUESS_PHOTO: [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), guess_photo),
                          CommandHandler("skip", lambda u, c: guess_photo(u, c))]
        },
        fallbacks=[CommandHandler("cancel", cancel_conv), CommandHandler("start", cancel_conv)],
        per_user=True
    )
    edit_timer_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_timer_cb, pattern=r"^edit_timer:")],
        states={EDIT_TIMER: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_timer_value)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)], per_user=True
    )
    edit_stars_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_stars_cb, pattern=r"^edit_stars:")],
        states={EDIT_STARS: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_stars_value)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)], per_user=True
    )
    # Edit lucky draw conversations
    edit_lucky_chance_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_lucky_chance_cb, pattern=r"^edit_lucky_chance:")],
        states={EDIT_LUCKY_CHANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_lucky_chance_value)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)], per_user=True
    )
    edit_lucky_winners_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_lucky_winners_cb, pattern=r"^edit_lucky_winners:")],
        states={EDIT_LUCKY_WINNERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_lucky_winners_value)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)], per_user=True
    )
    edit_lucky_duration_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_lucky_duration_cb, pattern=r"^edit_lucky_duration:")],
        states={EDIT_LUCKY_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_lucky_duration_value)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)], per_user=True
    )
    edit_lucky_prize_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_lucky_prize_cb, pattern=r"^edit_lucky_prize:")],
        states={EDIT_LUCKY_PRIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_lucky_prize_value)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)], per_user=True
    )
    edit_lucky_photo_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_lucky_photo_cb, pattern=r"^edit_lucky_photo:")],
        states={EDIT_LUCKY_PHOTO: [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), edit_lucky_photo_value),
                                  CommandHandler("skip", lambda u,c: edit_lucky_photo_value(u,c))]},
        fallbacks=[CommandHandler("cancel", cancel_conv)], per_user=True
    )
    edit_lucky_gift_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_lucky_gift_cb, pattern=r"^edit_lucky_gift:")],
        states={EDIT_LUCKY_GIFT: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_lucky_gift_value),
                                CommandHandler("skip", lambda u,c: edit_lucky_gift_value(u,c))]},
        fallbacks=[CommandHandler("cancel", cancel_conv)], per_user=True
    )

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("active", active_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("status", status_public))
    app.add_handler(auction_conv)
    app.add_handler(lucky_conv)
    app.add_handler(dice_conv)
    app.add_handler(guess_conv)
    app.add_handler(edit_timer_conv)
    app.add_handler(edit_stars_conv)
    app.add_handler(edit_lucky_chance_conv)
    app.add_handler(edit_lucky_winners_conv)
    app.add_handler(edit_lucky_duration_conv)
    app.add_handler(edit_lucky_prize_conv)
    app.add_handler(edit_lucky_photo_conv)
    app.add_handler(edit_lucky_gift_conv)

    # Callback handlers
    app.add_handler(CallbackQueryHandler(select_group_cb, pattern=r"^select_group:"))
    app.add_handler(CallbackQueryHandler(auction_mode_cb, pattern=r"^auction_mode:"))
    app.add_handler(CallbackQueryHandler(auction_default_cb, pattern=r"^auction_default:"))
    app.add_handler(CallbackQueryHandler(edit_game_cb, pattern=r"^edit_game:"))
    app.add_handler(CallbackQueryHandler(edit_lucky_cb, pattern=r"^edit_lucky:"))
    app.add_handler(CallbackQueryHandler(back_from_edit_cb, pattern=r"^back_from_edit:"))
    app.add_handler(CallbackQueryHandler(back_to_mode_cb, pattern=r"^back_to_mode:"))
    app.add_handler(CallbackQueryHandler(stop_game_cb, pattern=r"^stop_game:"))
    app.add_handler(CallbackQueryHandler(stop_lucky_cb, pattern=r"^stop_lucky:"))
    app.add_handler(CallbackQueryHandler(stop_dice_cb, pattern=r"^stop_dice:"))
    app.add_handler(CallbackQueryHandler(stop_guess_cb, pattern=r"^stop_guess:"))
    app.add_handler(CallbackQueryHandler(stats_game_cb, pattern=r"^stats_game:"))
    app.add_handler(CallbackQueryHandler(cancel_cb, pattern=r"^cancel_action$"))
