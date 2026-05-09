"""
YouTube Auto Poster Telegram Bot
Personalized bot - works only for the authorized user.
"""

import os
import logging
import asyncio
import tempfile
import json
import uuid
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

from youtube_uploader import YouTubeUploader
from config import BOT_TOKEN, AUTHORIZED_USER_ID, DOWNLOADS_DIR

DRAFTS_FILE = "drafts.json"

def get_drafts():
    if not os.path.exists(DRAFTS_FILE):
        return []
    try:
        with open(DRAFTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_local_draft(title, description, file_path):
    drafts = get_drafts()
    draft_id = str(uuid.uuid4())[:8]
    drafts.append({
        "id": draft_id,
        "title": title,
        "description": description,
        "file_path": file_path
    })
    with open(DRAFTS_FILE, "w", encoding="utf-8") as f:
        json.dump(drafts, f, indent=4)
    return draft_id

def remove_draft(draft_id):
    drafts = get_drafts()
    new_drafts = [d for d in drafts if d["id"] != draft_id]
    with open(DRAFTS_FILE, "w", encoding="utf-8") as f:
        json.dump(new_drafts, f, indent=4)

def get_draft(draft_id):
    for d in get_drafts():
        if d["id"] == draft_id:
            return d
    return None

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ── Conversation states ───────────────────────────────────────────────────────
WAITING_FOR_VIDEO = 0
WAITING_FOR_TITLE = 1
WAITING_FOR_DESCRIPTION = 2
CONFIRM_UPLOAD = 3

# ── Auth guard ────────────────────────────────────────────────────────────────
def authorized_only(func):
    """Decorator: only allow AUTHORIZED_USER_ID to use the bot."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if AUTHORIZED_USER_ID and str(user_id) != str(AUTHORIZED_USER_ID):
            await update.message.reply_text(
                "⛔ *Access Denied.*\nThis bot is private and personalised.",
                parse_mode=ParseMode.MARKDOWN,
            )
            logger.warning(f"Unauthorized access attempt by user_id={user_id}")
            return ConversationHandler.END
        return await func(update, context)
    return wrapper


# ── /start ────────────────────────────────────────────────────────────────────
@authorized_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uploader: YouTubeUploader = context.bot_data["uploader"]
    authenticated = uploader.is_authenticated()

    text = (
        "👋 *Welcome to your YouTube Auto Poster Bot!*\n\n"
        "This bot is personalised — it works only for you.\n\n"
    )

    if authenticated:
        channel = uploader.get_channel_name()
        text += (
            f"✅ *YouTube Connected:* `{channel}`\n\n"
            "📤 Send me a video file to upload it to your YouTube channel.\n"
            "Or use /help to see all commands."
        )
    else:
        text += (
            "⚠️ *YouTube account not connected yet.*\n\n"
            "Use /login to connect your YouTube account first."
        )

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END


# ── /login ────────────────────────────────────────────────────────────────────
@authorized_only
async def login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uploader: YouTubeUploader = context.bot_data["uploader"]

    await update.message.reply_text(
        "🔑 *YouTube Authentication*\n\n"
        "Generating your authentication link…",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        auth_url = uploader.get_auth_url()
        await update.message.reply_text(
            f"🌐 *Click the link below to authorise this bot to post on your YouTube channel:*\n\n"
            f"`{auth_url}`\n\n"
            "After you approve, you will be redirected to a page that says 'This site can't be reached'.\n"
            "That's normal! Just **copy the entire URL from your browser's address bar**.\n"
            "Send that URL here as `/auth <pasted_url>`",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error(f"Auth URL error: {e}")
        await update.message.reply_text(
            "❌ Failed to generate auth URL. Check your `client_secrets.json` file.",
            parse_mode=ParseMode.MARKDOWN,
        )

    return ConversationHandler.END


# ── /auth <code> ──────────────────────────────────────────────────────────────
@authorized_only
async def auth_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uploader: YouTubeUploader = context.bot_data["uploader"]
    args = context.args

    if not args:
        await update.message.reply_text(
            "❌ Usage: `/auth <pasted_url_or_code>`", parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    input_text = args[0].strip()
    
    # Try to extract 'code' from URL if they pasted the whole redirect URL
    if "?state=" in input_text and "&code=" in input_text:
        from urllib.parse import urlparse, parse_qs
        parsed_url = urlparse(input_text)
        code = parse_qs(parsed_url.query).get('code', [input_text])[0]
    else:
        code = input_text

    msg = await update.message.reply_text("⏳ Verifying your connection…")

    try:
        channel_name = uploader.exchange_code(code)
        await msg.edit_text(
            f"✅ *Successfully connected!*\n\n"
            f"📺 YouTube Channel: *{channel_name}*\n\n"
            f"You can now send me a video to upload it.",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error(f"Auth exchange error: {e}")
        await msg.edit_text(
            "❌ *Authentication failed.*\n"
            "The code may be invalid or expired. Try `/login` again.",
            parse_mode=ParseMode.MARKDOWN,
        )

    return ConversationHandler.END


# ── /status ───────────────────────────────────────────────────────────────────
@authorized_only
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uploader: YouTubeUploader = context.bot_data["uploader"]
    if uploader.is_authenticated():
        channel = uploader.get_channel_name()
        await update.message.reply_text(
            f"✅ *Connected to YouTube*\n📺 Channel: *{channel}*",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            "⚠️ *Not connected.* Use /login to connect your YouTube account.",
            parse_mode=ParseMode.MARKDOWN,
        )
    return ConversationHandler.END


# ── /logout ───────────────────────────────────────────────────────────────────
@authorized_only
async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uploader: YouTubeUploader = context.bot_data["uploader"]
    uploader.revoke_credentials()
    await update.message.reply_text(
        "🔓 *Logged out successfully.*\n"
        "Your YouTube credentials have been removed.\n"
        "Use /login to reconnect.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


# ── /help ─────────────────────────────────────────────────────────────────────
@authorized_only
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "📖 *YouTube Auto Poster — Commands*\n\n"
        "🔑 /login — Connect your YouTube account\n"
        "🔐 /auth `<code>` — Enter the auth code from Google\n"
        "📊 /status — Check connection status\n"
        "🔓 /logout — Disconnect YouTube account\n"
        "❓ /help — Show this message\n\n"
        "📤 *To upload a video:*\n"
        "Simply send me a video file — I'll walk you through the rest!",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


# ── VIDEO UPLOAD CONVERSATION ─────────────────────────────────────────────────

async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 1: Receive the video file."""
    user_id = update.effective_user.id
    if AUTHORIZED_USER_ID and str(user_id) != str(AUTHORIZED_USER_ID):
        return ConversationHandler.END

    uploader: YouTubeUploader = context.bot_data["uploader"]
    if not uploader.is_authenticated():
        await update.message.reply_text(
            "⚠️ *YouTube not connected.*\nUse /login first.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END

    # Support video files and documents (large files sent as documents)
    if update.message.video:
        file_obj = update.message.video
        filename = f"video_{file_obj.file_id}.mp4"
    elif update.message.document:
        file_obj = update.message.document
        filename = file_obj.file_name or f"video_{file_obj.file_id}.mp4"
    else:
        await update.message.reply_text("❌ Please send a valid video file.")
        return ConversationHandler.END

    # File size check (Telegram bot API limit: 2 GB local server / 50 MB via API)
    file_size_mb = (file_obj.file_size or 0) / (1024 * 1024)
    if file_size_mb > 2000:
        await update.message.reply_text(
            "❌ File too large. Maximum supported size is 2 GB."
        )
        return ConversationHandler.END

    msg = await update.message.reply_text(
        f"📥 *Downloading your video…*\n\n"
        f"📁 Size: `{file_size_mb:.1f} MB`",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        video_path = os.path.join(DOWNLOADS_DIR, filename)

        tg_file = await file_obj.get_file()
        await tg_file.download_to_drive(video_path)

        context.user_data["video_path"] = video_path
        context.user_data["video_filename"] = filename

        await msg.edit_text(
            "✅ *Video received!*\n\n"
            "📝 Now enter a *title* for your YouTube video:",
            parse_mode=ParseMode.MARKDOWN,
        )
        return WAITING_FOR_TITLE

    except Exception as e:
        logger.error(f"Video download error: {e}")
        await msg.edit_text(
            "❌ Failed to download the video. Please try again.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END


async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 2: Receive the video title."""
    title = update.message.text.strip()

    if len(title) < 1:
        await update.message.reply_text("❌ Title cannot be empty. Please enter a title:")
        return WAITING_FOR_TITLE

    if len(title) > 100:
        await update.message.reply_text(
            f"⚠️ Title too long ({len(title)}/100 chars). Please shorten it:"
        )
        return WAITING_FOR_TITLE

    context.user_data["title"] = title

    await update.message.reply_text(
        f"✅ *Title set:* `{title}`\n\n"
        "📄 Now enter a *description* for your video:\n"
        "_(or send /skip to leave it blank)_",
        parse_mode=ParseMode.MARKDOWN,
    )
    return WAITING_FOR_DESCRIPTION


async def receive_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 3: Receive the description."""
    description = update.message.text.strip()
    if description == "/skip":
        description = ""

    context.user_data["description"] = description

    return await show_confirmation(update, context)


async def skip_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Skip description."""
    context.user_data["description"] = ""
    return await show_confirmation(update, context)


async def show_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 4: Show confirmation before uploading."""
    title = context.user_data.get("title", "—")
    description = context.user_data.get("description", "") or "_(no description)_"
    filename = context.user_data.get("video_filename", "video.mp4")

    keyboard = [
        [
            InlineKeyboardButton("✅ Upload to YouTube (Public)", callback_data="upload_public"),
            InlineKeyboardButton("🔒 Upload to YouTube (Private)", callback_data="upload_private"),
        ],
        [
            InlineKeyboardButton("💾 Save to Bot Drafts", callback_data="save_draft_local"),
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_upload"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🎬 *Ready to Upload!*\n\n"
        f"📁 *File:* `{filename}`\n"
        f"📝 *Title:* `{title}`\n"
        f"📄 *Description:*\n{description}\n\n"
        "Confirm to post this video to your YouTube channel:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
    )
    return CONFIRM_UPLOAD


async def confirm_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle upload confirmation."""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel_upload":
        # Clean up downloaded file
        video_path = context.user_data.get("video_path")
        if video_path and os.path.exists(video_path):
            os.remove(video_path)
        context.user_data.clear()
        await query.edit_message_text(
            "❌ *Upload cancelled.*\nSend a new video whenever you're ready.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END

    video_path = context.user_data.get("video_path")
    title = context.user_data.get("title")
    description = context.user_data.get("description", "")

    if query.data == "save_draft_local":
        save_local_draft(title, description, video_path)
        context.user_data.clear()
        await query.edit_message_text(
            "💾 *Saved to Bot Drafts!*\n\n"
            "You can upload it later by using the /drafts command.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END

    # Proceed with upload
    privacy_status = "public" if query.data == "upload_public" else "private"

    uploader: YouTubeUploader = context.bot_data["uploader"]

    await query.edit_message_text(
        "⬆️ *Uploading to YouTube…*\n\n"
        "This may take a while depending on file size.\n"
        "Please wait…",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        video_id = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: uploader.upload_video(video_path, title, description, privacy_status=privacy_status),
        )

        video_url = f"https://www.youtube.com/watch?v={video_id}"

        await query.edit_message_text(
            "🎉 *Video uploaded successfully!*\n\n"
            f"📝 *Title:* `{title}`\n"
            f"🔗 *URL:* {video_url}\n\n"
            "Your video is now processing on YouTube.\n"
            "It may take a few minutes to become public.",
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        logger.error(f"Upload error: {e}")
        await query.edit_message_text(
            f"❌ *Upload failed.*\n\n"
            f"Error: `{str(e)}`\n\n"
            "Please try again or check /status.",
            parse_mode=ParseMode.MARKDOWN,
        )

    finally:
        # Cleanup local file
        if video_path and os.path.exists(video_path):
            os.remove(video_path)
        context.user_data.clear()

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the current operation."""
    video_path = context.user_data.get("video_path")
    if video_path and os.path.exists(video_path):
        os.remove(video_path)
    context.user_data.clear()
    await update.message.reply_text(
        "❌ *Operation cancelled.*",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


# ── Drafts ────────────────────────────────────────────────────────────────────
@authorized_only
async def list_drafts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    drafts = get_drafts()
    if not drafts:
        await update.message.reply_text("📭 You don't have any saved drafts.")
        return ConversationHandler.END

    text = "📁 *Your Saved Drafts:*\n\n"
    keyboard = []

    for i, d in enumerate(drafts, 1):
        text += f"{i}. *{d['title']}*\n"
        keyboard.append([InlineKeyboardButton(f"⬆️ Upload: {d['title']}", callback_data=f"draft_upload_{d['id']}")])
        keyboard.append([InlineKeyboardButton(f"❌ Delete: {d['title']}", callback_data=f"draft_delete_{d['id']}")])

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

async def handle_draft_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("draft_delete_"):
        draft_id = data.replace("draft_delete_", "")
        draft = get_draft(draft_id)
        if draft:
            if os.path.exists(draft["file_path"]):
                os.remove(draft["file_path"])
            remove_draft(draft_id)
            await query.edit_message_text("🗑️ Draft deleted.")
        else:
            await query.edit_message_text("❌ Draft not found.")

    elif data.startswith("draft_upload_"):
        draft_id = data.replace("draft_upload_", "")
        draft = get_draft(draft_id)
        if not draft:
            await query.edit_message_text("❌ Draft not found.")
            return ConversationHandler.END

        uploader: YouTubeUploader = context.bot_data["uploader"]
        if not uploader.is_authenticated():
            await query.edit_message_text("⚠️ *YouTube not connected.*\nUse /login first.", parse_mode=ParseMode.MARKDOWN)
            return ConversationHandler.END

        await query.edit_message_text(f"⬆️ *Uploading draft to YouTube (Public)…*\n\n📝 Title: {draft['title']}", parse_mode=ParseMode.MARKDOWN)

        try:
            video_id = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: uploader.upload_video(draft["file_path"], draft["title"], draft["description"], privacy_status="public"),
            )
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            await query.edit_message_text(
                "🎉 *Draft uploaded successfully!*\n\n"
                f"📝 *Title:* `{draft['title']}`\n"
                f"🔗 *URL:* {video_url}\n\n"
                "Your video is now processing on YouTube.",
                parse_mode=ParseMode.MARKDOWN,
            )

            if os.path.exists(draft["file_path"]):
                os.remove(draft["file_path"])
            remove_draft(draft_id)

        except Exception as e:
            logger.error(f"Draft upload error: {e}")
            await query.edit_message_text(
                f"❌ *Upload failed.*\n\nError: `{str(e)}`",
                parse_mode=ParseMode.MARKDOWN,
            )

    return ConversationHandler.END


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    logger.info("Starting YouTube Auto Poster Bot…")

    uploader = YouTubeUploader()
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .build()
    )
    app.bot_data["uploader"] = uploader

    # Upload conversation handler
    upload_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.VIDEO | filters.Document.VIDEO, receive_video),
            MessageHandler(filters.Document.MimeType("video/mp4") |
                           filters.Document.MimeType("video/quicktime") |
                           filters.Document.MimeType("video/x-matroska") |
                           filters.Document.MimeType("video/webm") |
                           filters.Document.MimeType("video/avi"), receive_video),
        ],
        states={
            WAITING_FOR_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title)
            ],
            WAITING_FOR_DESCRIPTION: [
                CommandHandler("skip", skip_description),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_description),
            ],
            CONFIRM_UPLOAD: [
                CallbackQueryHandler(confirm_upload, pattern="^(upload_public|upload_private|save_draft_local|cancel_upload)$")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("auth", auth_code))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("drafts", list_drafts))
    app.add_handler(CallbackQueryHandler(handle_draft_action, pattern="^draft_(upload|delete)_"))
    app.add_handler(upload_conv)

    logger.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        timeout=30,
        read_timeout=30,
        write_timeout=30,
    )


if __name__ == "__main__":
    main()
