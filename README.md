# 📁 Telegram File Bot

A production-grade Telegram bot for storing and sharing files. Users can search, browse by category, and use inline mode to share files from any chat. Admins can upload, manage categories, broadcast, and moderate users.

## Features

### For Users
- 🔍 **Search** — `/search <query>` to find files
- 📂 **Browse** — `/browse` to explore categories
- 🆕 **Latest** — `/latest` for recent uploads
- 🔥 **Popular** — `/popular` for most-downloaded files
- 💬 **Inline Mode** — Type `@botusername query` in any chat

### For Admins
- 📤 **Upload** — `/upload` (reply to a file or send after)
- 📦 **Batch Upload** — `/batch` to upload many files at once
- 📂 **Categories** — `/addcategory` to organize files
- 🗑️ **Delete** — `/delfile <id>` to remove files
- 📊 **Stats** — `/stats` for usage statistics
- 📣 **Broadcast** — `/broadcast <message>` to message all users
- 🚫 **Ban/Unban** — `/ban <user_id>` / `/unban <user_id>`

## Quick Start

### 1. Create a Bot

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the **bot token** you receive
4. **Enable inline mode:** Send `/setinline` to BotFather, select your bot, and set a placeholder text

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env`:
```env
BOT_TOKEN=your-token-from-botfather
ADMIN_IDS=your-telegram-user-id
```

> 💡 **Find your Telegram user ID:** Message [@userinfobot](https://t.me/userinfobot) on Telegram.

### 3. Run with Docker (Recommended)

```bash
docker-compose up -d
```

This starts PostgreSQL + the bot automatically.

### 4. Run Locally (Alternative)

```bash
# Install PostgreSQL and create a database first
# Then:

python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

pip install -r requirements.txt
python -m bot
```

## Project Structure

```
TG bot/
├── bot/
│   ├── __main__.py        # Entry point
│   ├── config.py          # Settings from .env
│   ├── db/
│   │   ├── engine.py      # Async SQLAlchemy engine
│   │   ├── models.py      # ORM models
│   │   └── queries.py     # Database queries
│   ├── handlers/
│   │   ├── user.py        # /start, /help, menus
│   │   ├── search.py      # /search, /browse, /latest, /popular
│   │   ├── admin.py       # Admin commands
│   │   ├── callbacks.py   # File detail & download
│   │   └── inline.py      # Inline query handler
│   ├── keyboards/
│   │   └── inline.py      # Inline keyboard builders
│   ├── middlewares/
│   │   ├── db.py          # DB session injection
│   │   ├── auth.py        # Admin authentication
│   │   └── throttle.py    # Rate limiting
│   └── utils/
│       ├── formatting.py  # Message formatters
│       └── pagination.py  # Pagination helper
├── .env.example
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Optional: Force Channel Subscription

To require users to join your channel before using the bot:

1. Create a Telegram channel
2. Add the bot as an **admin** in the channel
3. Set in `.env`:
   ```env
   FORCE_SUB_CHANNEL=@yourchannel
   ```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Bot Framework | aiogram 3.x |
| Database | PostgreSQL 16 |
| ORM | SQLAlchemy 2.0 (async) |
| Config | pydantic-settings |
| Container | Docker + docker-compose |
