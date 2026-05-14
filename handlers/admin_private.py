"""Admin private chat handlers – with dice game, stats, status."""
from telegram import Update
from telegram.ext import (
    CommandHandler, CallbackQueryHandler, ConversationHandler,
    MessageHandler, filters, ContextTypes
)
from config import Config
from database import Database
from keyboards import *
import logging, html

logger = logging.getLogger(__name__)

ASK_TIMER, ASK_STARS, ASK_DESCRIPTION = range(3)
ASK_CHANCE, ASK_PRIZE, ASK_PHOTO = range(10, 13)
DICE_EMOJI, DICE_VALUE, DICE_PRIZE = range(20, 23)
EDIT_TIMER, EDIT_STARS = range(30, 32)

db = Database()

async def is_admin(uid): return uid in Config.ADMIN_IDS

# ---------- /status (public) ----------
async def status_public(update: Update, context: ContextTypes.DEFAULT_TYPE):
    counts = await db.get_active_game_counts()
    auctions = counts['auctions']
    lucky = counts['lucky_draws']
    dice = counts['dice']
    if auctions == 0 and lucky == 0 and dice == 0:
        await update.message.reply_text("📊 <b>Статус бота:</b> нет активных игр.", parse_mode="HTML")
    else:
        parts = []
        if auctions: parts.append(f"Аукционы: {auctions}")
        if lucky: parts.append(f"Lucky Draw: {lucky}")
        if dice: parts.append(f"Кости: {dice}")
        text = f"📊 <b>Статус бота:</b>\n" + "\n".join(parts)
        await update.message.reply_text(text, parse_mode="HTML")

# ---------- /start, /active, /stop, /stats (admin only) ----------
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
    if not await is_admin(update.effective_user.id):
        return
    games = await db.get_all_active_games()
    draws = await db.get_all_active_lucky_draws()
    dice_games = await db.get_all_active_dice_games()
    if not games and not draws and not dice_games:
        await update.message.reply_text("Нет активных игр.")
        return
    await update.message.reply_text("🏃 Активные игры:", reply_markup=build_active_games_keyboard(games, draws, dice_games), parse_mode="HTML")

async def stop_cmd(update: Update, context):
    await active_cmd(update, context)

async def stats_cmd(update: Update, context):
    if not await is_admin(update.effective_user.id):
        return
    games = await db.get_all_active_games()
    if not games:
        await update.message.reply_text("Нет активных аукционов.")
        return
    text = "📊 <b>Статистика аукционов:</b>\n"
    for g in games:
        leader = g.get('leader_name', 'Нет')
        bids = g.get('bid_count', 0)
        stars = g.get('total_stars', 0)
        text += f"\nГруппа <code>{g['chat_id']}</code>: лидер {leader}, ставок: {bids}, звёзд: {stars}"
    await update.message.reply_text(text, parse_mode="HTML")

# ---------- group select -> mode ----------
async def select_group_cb(update: Update, context):
    query = update.callback_query; await query.answer()
    if not await is_admin(update.effective_user.id): return await query.edit_message_text("⛔ Нет доступа.")
    chat_id = int(query.data.split(":")[1])
    context.user_data["selected_chat_id"] = chat_id
    await query.edit_message_text(f"📱 Группа <code>{chat_id}</code>\nВыберите режим:", reply_markup=build_game_mode_keyboard(chat_id), parse_mode="HTML")

# ---------- Auction ----------
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
        await context.bot.send_message(
            chat_id,
            f"🎉 <b>Ивент начался!</b>\n\n"
            f"⭐ 1 сообщение в чате = {stars} звёзд.\n"
            f"⏱ Цель: продержаться {mins} мин без перебива.\n"
            f"{desc_line}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Announce fail: {e}")
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
        if not stars or any(not (1 <= s <= 999) for s in stars):
            raise ValueError
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
        await context.bot.send_message(
            chat_id,
            f"🎉 <b>Ивент начался!</b>\n\n"
            f"⭐ 1 сообщение в чате = {', '.join(map(str, stars))} звёзд.\n"
            f"⏱ Цель: продержаться {mins} мин без перебива.\n"
            f"{desc_line}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Announce fail: {e}")
    return ConversationHandler.END

# ---------- Edit auction ----------
async def edit_game_cb(update: Update, context):
    query = update.callback_query; await query.answer()
    if not await is_admin(update.effective_user.id): return
    chat_id = int(query.data.split(":")[1])
    context.user_data["edit_chat_id"] = chat_id
    await query.edit_message_text(
        f"✏️ Изменить аукцион в группе <code>{chat_id}</code>",
        reply_markup=build_edit_game_keyboard(chat_id),
        parse_mode="HTML"
    )

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
    mins = new_timer // 60
    secs = new_timer % 60
    duration_str = f"{mins} мин" if secs == 0 else f"{mins} мин {secs} сек"
    try:
        await context.bot.send_message(
            chat_id,
            f"⏱ <b>Время изменено!</b> Новая длительность: {duration_str}.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Failed to notify group about timer change: {e}")
    await update.message.reply_text(f"✅ Время изменено на {new_timer} сек. (применится к следующей ставке).")
    return ConversationHandler.END

async def edit_stars_value(update: Update, context):
    text = update.message.text.strip()
    try:
        stars = [int(s.strip()) for s in text.split(",") if s.strip()]
        if not stars or any(not (1 <= s <= 999) for s in stars):
            raise ValueError
        stars = sorted(set(stars))
    except:
        await update.message.reply_text("❌ Введите положительные числа: 1,2,3")
        return EDIT_STARS
    chat_id = context.user_data["edit_chat_id"]
    await db.update_game_settings(chat_id, stars=stars)
    await update.message.reply_text(f"✅ Разрешённые звёзды изменены на {', '.join(map(str, stars))}.")
    return ConversationHandler.END

# ---------- Lucky Draw ----------
async def lucky_draw_cb(update: Update, context) -> int:
    query = update.callback_query; await query.answer()
    chat_id = int(query.data.split(":")[1])
    context.user_data["draw_chat_id"] = chat_id
    await query.edit_message_text("🎰 Введите шанс выигрыша (0-100)%:")
    return ASK_CHANCE

async def ask_chance(update: Update, context) -> int:
    text = update.message.text.strip()
    if not text.isdigit() or not (0 <= int(text) <= 100):
        await update.message.reply_text("❌ Введите число от 0 до 100:")
        return ASK_CHANCE
    context.user_data["draw_chance"] = int(text)
    await update.message.reply_text("🎁 Введите описание приза:")
    return ASK_PRIZE

async def ask_prize(update: Update, context) -> int:
    prize = update.message.text.strip()
    if not prize:
        await update.message.reply_text("❌ Приз не может быть пустым.")
        return ASK_PRIZE
    context.user_data["draw_prize"] = prize
    await update.message.reply_text("🖼 Отправьте фото для объявления (или /skip):")
    return ASK_PHOTO

async def ask_photo(update: Update, context) -> int:
    if update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
        context.user_data["draw_photo"] = photo_file_id
        await update.message.reply_text("✅ Фото получено, Lucky Draw активируется.")
    elif update.message.text and update.message.text.lower() == "/skip":
        context.user_data["draw_photo"] = None
    else:
        await update.message.reply_text("❌ Отправьте фото или /skip.")
        return ASK_PHOTO

    chat_id = context.user_data["draw_chat_id"]
    chance = context.user_data["draw_chance"]
    prize = context.user_data["draw_prize"]
    photo_file_id = context.user_data.get("draw_photo")
    await db.create_lucky_draw(chat_id, chance, prize, photo_file_id)
    await update.message.reply_text(f"✅ Lucky Draw активирован в {chat_id}!")

    try:
        caption = f"🎰 <b>Lucky Draw!</b>\n🎁 Приз: {html.escape(prize)}\n🎲 Шанс: {chance}% за каждое сообщение."
        if photo_file_id:
            await context.bot.send_photo(chat_id, photo_file_id, caption=caption, parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id, caption, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Failed to announce Lucky Draw: {e}")
    return ConversationHandler.END

# ---------- Dice Game ----------
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
    if emoji == "🎰":
        max_val = 64
        hint = " (64 = 777)"
    elif emoji in ("🎲", "🎯"):
        max_val = 6
        hint = ""
    else:
        max_val = 5
        hint = ""
    await query.edit_message_text(f"🎯 Введите выигрышное значение (от 1 до {max_val}){hint}:")
    return DICE_VALUE

async def dice_value_entered(update: Update, context) -> int:
    text = update.message.text.strip()
    emoji = context.user_data["dice_emoji"]
    if emoji == "🎰":
        max_val = 64
    elif emoji in ("🎲", "🎯"):
        max_val = 6
    else:
        max_val = 5
    if not text.isdigit() or not (1 <= int(text) <= max_val):
        await update.message.reply_text(f"❌ Введите число от 1 до {max_val}:")
        return DICE_VALUE
    context.user_data["dice_value"] = int(text)
    await update.message.reply_text("🎁 Введите описание приза:")
    return DICE_PRIZE

async def dice_prize_entered(update: Update, context) -> int:
    prize = update.message.text.strip()
    if not prize:
        await update.message.reply_text("❌ Приз не может быть пустым.")
        return DICE_PRIZE
    chat_id = context.user_data["dice_chat_id"]
    emoji = context.user_data["dice_emoji"]
    value = context.user_data["dice_value"]
    await db.create_dice_game(chat_id, emoji, value, prize)
    await update.message.reply_text(f"✅ Игра с {emoji} на {value} создана в группе {chat_id}!")
    try:
        await context.bot.send_message(
            chat_id,
            f"🎲 <b>Игра начата!</b> Отправьте {emoji}, чтобы попробовать выбить {value} и выиграть: {html.escape(prize)}.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Failed to announce dice game: {e}")
    return ConversationHandler.END

# ---------- Stop handlers ----------
async def stop_game_cb(update: Update, context):
    query = update.callback_query; await query.answer()
    if not await is_admin(update.effective_user.id): return
    chat_id = int(query.data.split(":")[1])
    for j in context.job_queue.jobs():
        if j.name and (j.name.startswith(f"auction_{chat_id}") or j.name.startswith(f"countdown_{chat_id}")):
            j.schedule_removal()
    await db.deactivate_game(chat_id)
    await query.edit_message_text(f"🛑 Ивент остановлен в {chat_id}.")
    try: await context.bot.send_message(chat_id, "🛑 Ивент остановлен администратором.")
    except: pass

async def stop_lucky_cb(update: Update, context):
    query = update.callback_query; await query.answer()
    if not await is_admin(update.effective_user.id): return
    chat_id = int(query.data.split(":")[1])
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

async def stats_game_cb(update: Update, context):
    query = update.callback_query; await query.answer()
    chat_id = int(query.data.split(":")[1])
    game = await db.get_active_game(chat_id)
    if not game:
        await query.edit_message_text("Аукцион не активен.")
        return
    await query.edit_message_text(
        f"📊 <b>Статистика аукциона в {chat_id}</b>\n"
        f"Лидер: {game.get('leader_name', 'Нет')}\n"
        f"Ставок: {game.get('bid_count', 0)}\n"
        f"Звёзд: {game.get('total_stars', 0)}",
        parse_mode="HTML"
    )

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
            ASK_PHOTO: [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), ask_photo),
                        CommandHandler("skip", lambda u, c: ask_photo(u, c))]
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
    edit_timer_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_timer_cb, pattern=r"^edit_timer:")],
        states={
            EDIT_TIMER: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_timer_value)]
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        per_user=True
    )
    edit_stars_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_stars_cb, pattern=r"^edit_stars:")],
        states={
            EDIT_STARS: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_stars_value)]
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        per_user=True
    )

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("active", active_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("status", status_public))
    app.add_handler(auction_conv)
    app.add_handler(lucky_conv)
    app.add_handler(dice_conv)
    app.add_handler(edit_timer_conv)
    app.add_handler(edit_stars_conv)

    app.add_handler(CallbackQueryHandler(select_group_cb, pattern=r"^select_group:"))
    app.add_handler(CallbackQueryHandler(auction_mode_cb, pattern=r"^auction_mode:"))
    app.add_handler(CallbackQueryHandler(auction_default_cb, pattern=r"^auction_default:"))
    app.add_handler(CallbackQueryHandler(edit_game_cb, pattern=r"^edit_game:"))
    app.add_handler(CallbackQueryHandler(back_from_edit_cb, pattern=r"^back_from_edit:"))
    app.add_handler(CallbackQueryHandler(back_to_mode_cb, pattern=r"^back_to_mode:"))
    app.add_handler(CallbackQueryHandler(stop_game_cb, pattern=r"^stop_game:"))
    app.add_handler(CallbackQueryHandler(stop_lucky_cb, pattern=r"^stop_lucky:"))
    app.add_handler(CallbackQueryHandler(stop_dice_cb, pattern=r"^stop_dice:"))
    app.add_handler(CallbackQueryHandler(stats_game_cb, pattern=r"^stats_game:"))
    app.add_handler(CallbackQueryHandler(cancel_cb, pattern=r"^cancel_action$"))