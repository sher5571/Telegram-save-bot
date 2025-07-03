import os
import logging
import asyncio
import sqlite3
from datetime import datetime, timedelta
from urllib.parse import urlparse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import yt_dlp
import aiofiles

# Logging sozlash
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot tokeni va admin ID
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))  # Admin ID ni environment variable dan oling

# Majburiy kanallar
REQUIRED_CHANNELS = [
    {'name': '+ Kanal', 'username': '@Foydali_botlar_uzbek'},
    {'name': '+ Kanal', 'username': '@kinolar_ozbek_tili'},
    {'name': '+ Kanal', 'username': '@shablonlarii'}
]

# Ma'lumotlar bazasi yaratish
def init_db():
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    
    # Foydalanuvchilar jadvali
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, 
                  join_date TIMESTAMP, last_active TIMESTAMP, download_count INTEGER DEFAULT 0)''')
    
    # Yuklab olishlar jadvali
    c.execute('''CREATE TABLE IF NOT EXISTS downloads
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, 
                  video_url TEXT, title TEXT, download_date TIMESTAMP)''')
    
    conn.commit()
    conn.close()

class YTDLPLogger:
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): logger.error(msg)

def add_user_to_db(user_id, username, first_name):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, join_date, last_active) VALUES (?, ?, ?, ?, ?)",
              (user_id, username, first_name, datetime.now(), datetime.now()))
    conn.commit()
    conn.close()

def update_user_activity(user_id):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("UPDATE users SET last_active = ? WHERE user_id = ?", (datetime.now(), user_id))
    conn.commit()
    conn.close()

def increment_download_count(user_id):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("UPDATE users SET download_count = download_count + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def log_download(user_id, video_url, title):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT INTO downloads (user_id, video_url, title, download_date) VALUES (?, ?, ?, ?)",
              (user_id, video_url, title, datetime.now()))
    conn.commit()
    conn.close()

async def check_subscription(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    """Foydalanuvchi barcha kanallarga obuna bo'lganmi tekshirish"""
    for channel in REQUIRED_CHANNELS:
        try:
            member = await context.bot.get_chat_member(f"@{channel['username']}", user_id)
            if member.status in ['left', 'kicked']:
                return False
        except Exception as e:
            logger.error(f"Kanal tekshirishda xatolik: {e}")
            return False
    return True

def get_subscription_keyboard():
    """Obuna bo'lish tugmalari"""
    keyboard = []
    for channel in REQUIRED_CHANNELS:
        keyboard.append([InlineKeyboardButton(f"+ {channel['name']}", url=f"https://t.me/{channel['username']}")])
    keyboard.append([InlineKeyboardButton("✅ Tekshirish", callback_data="check_subscription")])
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard():
    """Admin uchun klaviatura"""
    keyboard = [
        [KeyboardButton("📊 Statistika"), KeyboardButton("📢 Xabar yuborish")],
        [KeyboardButton("👥 Foydalanuvchilar"), KeyboardButton("🏆 Top 20")],
        [KeyboardButton("🔙 Oddiy rejim")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start komandasi"""
    user = update.effective_user
    add_user_to_db(user.id, user.username, user.first_name)
    
    if user.id == ADMIN_ID:
        keyboard = [[KeyboardButton("👨‍💻 Admin rejimi"), KeyboardButton("ℹ️ Yordam")]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "🔥 Salom Admin!\n\n"
            "YouTube video yuklovchi botga xush kelibsiz!\n"
            "YouTube havolasini yuboring va men sizga videoni yuklab beraman.",
            reply_markup=reply_markup
        )
    else:
        # Obuna tekshirish
        if not await check_subscription(context, user.id):
            await update.message.reply_text(
                "🔒 Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:",
                reply_markup=get_subscription_keyboard()
            )
            return
        
        await update.message.reply_text(
            "🔥 Salom!\n\n"
            "YouTube video yuklovchi botga xush kelibsiz!\n"
            "YouTube havolasini yuboring va men sizga videoni yuklab beraman.\n\n"
            "📝 Qo'llab-quvvatlanadigan formatlar:\n"
            "• MP4 (video)\n"
            "• MP3 (audio)\n"
            "• Turli sifatlar"
        )

async def admin_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin rejimi"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Sizda admin huquqlari yo'q!")
        return
    
    await update.message.reply_text(
        "👨‍💻 Admin rejimi yoqildi!",
        reply_markup=get_admin_keyboard()
    )

async def normal_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Oddiy rejim"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    keyboard = [[KeyboardButton("👨‍💻 Admin rejimi"), KeyboardButton("ℹ️ Yordam")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("🔙 Oddiy rejim", reply_markup=reply_markup)

async def get_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Statistika olish"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    
    # Umumiy foydalanuvchilar
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    
    # Bugungi qo'shilganlar
    today = datetime.now().date()
    c.execute("SELECT COUNT(*) FROM users WHERE DATE(join_date) = ?", (today,))
    today_users = c.fetchone()[0]
    
    # Haftalik qo'shilganlar
    week_ago = datetime.now() - timedelta(days=7)
    c.execute("SELECT COUNT(*) FROM users WHERE join_date >= ?", (week_ago,))
    week_users = c.fetchone()[0]
    
    # Oylik qo'shilganlar
    month_ago = datetime.now() - timedelta(days=30)
    c.execute("SELECT COUNT(*) FROM users WHERE join_date >= ?", (month_ago,))
    month_users = c.fetchone()[0]
    
    # Yillik qo'shilganlar
    year_ago = datetime.now() - timedelta(days=365)
    c.execute("SELECT COUNT(*) FROM users WHERE join_date >= ?", (year_ago,))
    year_users = c.fetchone()[0]
    
    # Umumiy yuklab olishlar
    c.execute("SELECT COUNT(*) FROM downloads")
    total_downloads = c.fetchone()[0]
    
    conn.close()
    
    stats_text = f"""📊 **BOT STATISTIKASI**

👥 **Foydalanuvchilar:**
• Jami: {total_users}
• Bugun: {today_users}
• Hafta: {week_users}
• Oy: {month_users}
• Yil: {year_users}

⬇️ **Yuklab olishlar:**
• Jami: {total_downloads}
"""
    
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def get_top_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Top 20 foydalanuvchilar"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT first_name, username, download_count FROM users ORDER BY download_count DESC LIMIT 20")
    top_users = c.fetchall()
    conn.close()
    
    if not top_users:
        await update.message.reply_text("📊 Hali statistika yo'q!")
        return
    
    text = "🏆 **TOP 20 FOYDALANUVCHILAR**\n\n"
    for i, (first_name, username, downloads) in enumerate(top_users, 1):
        username_text = f"@{username}" if username else "Username yo'q"
        text += f"{i}. {first_name} ({username_text}): {downloads} ta\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xabar yuborish"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    await update.message.reply_text("📢 Barcha foydalanuvchilarga yubormoqchi bo'lgan xabaringizni yozing:")
    context.user_data['waiting_for_broadcast'] = True

async def subscription_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obuna tekshirish callback"""
    query = update.callback_query
    await query.answer()
    
    if await check_subscription(context, query.from_user.id):
        await query.edit_message_text(
            "✅ Obuna tasdiqlandi!\n\n"
            "Endi YouTube havolasini yuboring va men sizga videoni yuklab beraman."
        )
    else:
        await query.edit_message_text(
            "❌ Siz hali barcha kanallarga obuna bo'lmadingiz!\n"
            "Iltimos, avval obuna bo'ling.",
            reply_markup=get_subscription_keyboard()
        )

async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Video yuklab olish"""
    user_id = update.effective_user.id
    
    # Obuna tekshirish (admin emas bo'lsa)
    if user_id != ADMIN_ID and not await check_subscription(context, user_id):
        await update.message.reply_text(
            "🔒 Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:",
            reply_markup=get_subscription_keyboard()
        )
        return
    
    # Broadcast xabar kutilayotgan bo'lsa
    if context.user_data.get('waiting_for_broadcast') and user_id == ADMIN_ID:
        await broadcast_to_all_users(update, context)
        return
    
    url = update.message.text
    
    # URL tekshirish
    if not ("youtube.com" in url or "youtu.be" in url):
        await update.message.reply_text("❌ Iltimos, to'g'ri YouTube havolasini yuboring!")
        return
    
    update_user_activity(user_id)
    
    # Yuklab olish jarayoni
    progress_msg = await update.message.reply_text("⏳ Video yuklab olinmoqda...")
    
    try:
        ydl_opts = {
            'format': 'best[height<=720]',
            'outtmpl': '%(title)s.%(ext)s',
            'logger': YTDLPLogger(),
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Video ma'lumotlarini olish
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Noma\'lum video')
            duration = info.get('duration', 0)
            filesize = info.get('filesize', 0)
            
            # Hajm tekshirish (50MB limit)
            if filesize and filesize > 50 * 1024 * 1024:
                await progress_msg.edit_text("❌ Video hajmi 50MB dan katta! Kichikroq video tanlang.")
                return
            
            # Video yuklab olish
            await progress_msg.edit_text("📥 Video yuklab olinmoqda...")
            ydl.download([url])
            
            filename = ydl.prepare_filename(info)
            
            # Telegram'ga yuborish
            await progress_msg.edit_text("📤 Video yuborilmoqda...")
            
            # Video ma'lumotlari
            file_size = os.path.getsize(filename) if os.path.exists(filename) else 0
            size_mb = round(file_size / (1024 * 1024), 2)
            
            # Caption yaratish
            caption = f"📹 **{title}**\n\n"
            caption += f"📊 Hajm: {size_mb} MB\n"
            caption += f"⏱ Davomiyligi: {duration//60}:{duration%60:02d}\n"
            caption += f"🤖 @{context.bot.username}"
            
            # Videoni yuborish
            with open(filename, 'rb') as video:
                await update.message.reply_video(
                    video=video,
                    caption=caption,
                    parse_mode='Markdown'
                )
            
            # Statistika yangilash
            increment_download_count(user_id)
            log_download(user_id, url, title)
            
            # Faylni o'chirish
            if os.path.exists(filename):
                os.remove(filename)
            
            await progress_msg.delete()
            
    except Exception as e:
        logger.error(f"Video yuklab olishda xatolik: {e}")
        await progress_msg.edit_text(f"❌ Video yuklab olishda xatolik yuz berdi!")

async def broadcast_to_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Barcha foydalanuvchilarga xabar yuborish"""
    message_text = update.message.text
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    conn.close()
    
    context.user_data['waiting_for_broadcast'] = False
    
    sent_count = 0
    failed_count = 0
    
    progress_msg = await update.message.reply_text("📢 Xabar yuborilmoqda...")
    
    for user_id in users:
        try:
            await context.bot.send_message(user_id[0], message_text)
            sent_count += 1
        except Exception as e:
            failed_count += 1
            logger.error(f"Xabar yuborishda xatolik {user_id[0]}: {e}")
    
    await progress_msg.edit_text(
        f"📊 Xabar yuborish yakunlandi!\n\n"
        f"✅ Yuborildi: {sent_count}\n"
        f"❌ Yuborilmadi: {failed_count}"
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Matn xabarlarni qayta ishlash"""
    text = update.message.text
    
    if text == "👨‍💻 Admin rejimi":
        await admin_mode(update, context)
    elif text == "🔙 Oddiy rejim":
        await normal_mode(update, context)
    elif text == "📊 Statistika":
        await get_statistics(update, context)
    elif text == "🏆 Top 20":
        await get_top_users(update, context)
    elif text == "📢 Xabar yuborish":
        await broadcast_message(update, context)
    elif text == "ℹ️ Yordam":
        await update.message.reply_text(
            "🤖 **YouTube Video Yuklovchi Bot**\n\n"
            "📝 **Qo'llanma:**\n"
            "1. YouTube video havolasini yuboring\n"
            "2. Bot videoni yuklab oladi\n"
            "3. Sizga yuboradi\n\n"
            "⚠️ **Cheklovlar:**\n"
            "• Maksimal hajm: 50MB\n"
            "• Faqat YouTube\n"
            "• Obuna majburiy\n\n"
            "🔗 **Qo'llab-quvvatlash:** @admin",
            parse_mode='Markdown'
        )
    else:
        await download_video(update, context)

def main():
    """Asosiy funksiya"""
    init_db()
    
    application = Application.builder().token(TOKEN).build()
    
    # Handlerlar
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(subscription_check, pattern="check_subscription"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Botni ishga tushirish
    print("🤖 Bot ishga tushdi!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
