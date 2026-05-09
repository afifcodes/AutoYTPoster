"""
Configuration for YouTube Auto Poster Bot.
Edit values here or set them as environment variables.
"""

import os

# ── Telegram Bot ──────────────────────────────────────────────────────────────

# Your Telegram bot token
BOT_TOKEN = os.getenv("BOT_TOKEN", "8331860568:AAG9C1W2VO2C-vLkL2IfTMiKi7aCz0ZTtxI")

# YOUR Telegram user ID — the bot will ONLY respond to this user.
# Find your user ID by messaging @userinfobot on Telegram.
# Set this to your numeric Telegram user ID (e.g. "123456789")
AUTHORIZED_USER_ID = os.getenv("AUTHORIZED_USER_ID", "")  # ← FILL THIS IN

# ── YouTube OAuth ─────────────────────────────────────────────────────────────

# Path to the client_secrets.json downloaded from Google Cloud Console
CLIENT_SECRETS_FILE = os.getenv("CLIENT_SECRETS_FILE", "client_secrets.json")

# Where to store the OAuth token after first login
TOKEN_FILE = os.getenv("TOKEN_FILE", "youtube_token.pkl")

# OAuth scopes required for uploading videos
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

# ── Storage ───────────────────────────────────────────────────────────────────

# Temp directory for downloaded videos before uploading
DOWNLOADS_DIR = os.getenv("DOWNLOADS_DIR", "downloads")
