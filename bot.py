import os
import glob
import asyncio
import logging
import threading
from urllib.parse import urlparse
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
import yt_dlp

# Minimal web server to satisfy cloud health checks
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Bot is alive and running!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app_web.run(host="0.0.0.0", port=port)

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8784168600:AAGDEuCyiuVnG9MTxiDOvzZZPiSvZnXm9CE"
CHANNEL_ID = -1004318641164
CHANNEL_USERNAME = "gokuladmin1"

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def is_youtube_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
        return parsed.netloc in [
            "www.youtube.com",
            "youtube.com",
            "m.youtube.com",
            "youtu.be",
        ]
    except Exception:
        return False


def run_yt_dlp(ydl_opts: dict, url: str) -> dict:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=True)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Send me any YouTube link, choose MP4 or MP3, and I will upload it directly to the channel!"
    )


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not is_youtube_url(url):
        await update.message.reply_text("❌ Please send a valid YouTube link.")
        return

    context.user_data["pending_url"] = url
    keyboard = [
        [
            InlineKeyboardButton("🎬 MP4 (Video + Audio)", callback_data="download_mp4"),
            InlineKeyboardButton("🎵 MP3 (Audio)", callback_data="download_mp3"),
        ]
    ]
    await update.message.reply_text(
        "Choose format to download:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    url = context.user_data.get("pending_url")
    if not url:
        await query.edit_message_text("Session expired. Please send the link again.")
        return

    choice = query.data
    await query.edit_message_text("⏳ Processing and merging with FFmpeg... Please wait.")

    user_id = query.from_user.id
    out_template = os.path.join(DOWNLOAD_DIR, f"{user_id}_%(id)s.%(ext)s")

    if choice == "download_mp3":
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": out_template,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
            "quiet": True,
            "no_warnings": True,
        }
    else:
        ydl_opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": out_template,
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
        }

    downloaded_file = None
    try:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, run_yt_dlp, ydl_opts, url)

        video_id = info.get("id")
        matches = glob.glob(os.path.join(DOWNLOAD_DIR, f"{user_id}_{video_id}.*"))
        if not matches:
            await query.edit_message_text("❌ Failed to process media.")
            return

        downloaded_file = matches[0]
        file_size_mb = os.path.getsize(downloaded_file) / (1024 * 1024)

        if file_size_mb > 50:
            await query.edit_message_text(
                f"❌ File size ({file_size_mb:.1f} MB) exceeds Telegram's 50MB bot upload limit."
            )
            return

        title = info.get("title", "Media")
        duration = info.get("duration")

        await query.edit_message_text("📤 Uploading merged video to channel...")

        with open(downloaded_file, "rb") as media:
            if choice == "download_mp3":
                sent_post = await context.bot.send_audio(
                    chat_id=CHANNEL_ID,
                    audio=media,
                    title=title,
                    duration=duration,
                    caption=f"🎵 **{title}**\n👤 Requested by: {query.from_user.first_name}",
                    parse_mode="Markdown",
                )
            else:
                sent_post = await context.bot.send_video(
                    chat_id=CHANNEL_ID,
                    video=media,
                    caption=f"🎬 **{title}**\n👤 Requested by: {query.from_user.first_name}",
                    supports_streaming=True,
                    parse_mode="Markdown",
                )

        post_link = f"https://t.me/{CHANNEL_USERNAME}/{sent_post.message_id}"
        result_buttons = [
            [InlineKeyboardButton("👀 Open in Channel", url=post_link)]
        ]

        await query.edit_message_text(
            f"✅ **Uploaded successfully!**\n\n"
            f"📁 **Title:** {title}\n"
            f"📦 **Size:** {file_size_mb:.1f} MB",
            reply_markup=InlineKeyboardMarkup(result_buttons),
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.error(f"Error: {e}")
        await query.edit_message_text(f"❌ An error occurred: {str(e)}")

    finally:
        if downloaded_file and os.path.exists(downloaded_file):
            try:
                os.remove(downloaded_file)
            except OSError:
                pass


def main():
    # Start the dummy web server in a separate background thread
    threading.Thread(target=run_web, daemon=True).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_handler(CallbackQueryHandler(button_callback))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
  
