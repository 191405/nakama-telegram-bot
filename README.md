# Nakama Network — Telegram Anime Bot & Web Streaming Platform

A production-grade anime archiving and web streaming platform backed by Telegram's cloud storage. Includes an automated Telegram bot, an AniList-enriched web streaming platform (inspired by Animepahe & Lucifer Donghua), and an MTProto byte-range streaming gateway capable of playing high-bitrate anime releases directly in browser HTML5 players.

---

## 🏗️ Architecture Overview

```
                          ┌───────────────────────────┐
                          │    Browser Web Client     │
                          │   (Animepahe / Lucifer)   │
                          └─────────────┬─────────────┘
                                        │
                         HTTP REST / 206 Byte-Range
                                        │
                                        ▼
┌───────────────────────┐     ┌───────────────────────────┐     ┌───────────────────────┐
│     Telegram Bot      │     │    Web Streaming Gateway  │     │   Private Telegram    │
│    (aiogram 3.x)      │◄───►│       (aiohttp 3.x)       │◄───►│    Storage Channel    │
│  User & Admin Arena   │     │  Telethon MTProto Client  │     │  (Unlimited Storage)  │
└──────────┬────────────┘     └─────────────┬─────────────┘     └───────────────────────┘
           │                                │
           │      Shared Database Layer     │
           └────────────────►◄──────────────┘
                    SQLite WAL / PostgreSQL
```

### Core Components
1. **Web Streaming Gateway (`server/app.py`)**:
   - High-performance `aiohttp` server exposing REST endpoints (`/api/catalog`, `/api/series/{name}`).
   - **Telegram MTProto Streaming Engine**: Implements HTTP 206 Partial Content range streaming via Telethon. Bypasses the 20MB bot API barrier, streaming 100MB–2GB files chunk-by-chunk directly into browser memory.
   - Hosts the single-page application (SPA) with zero external frameworks.
2. **Telegram Bot (`bot/`)**:
   - `aiogram 3.x` long-polling bot for search, anime discovery, admin uploads, and community interactions.
   - Intercepts files in the storage channel and automatically indexes them into the database.
3. **Database Layer (`bot/db/`)**:
   - Asynchronous SQLAlchemy 2.0 with automated migrations.
   - Out-of-the-box support for **SQLite with WAL mode** (Write-Ahead Logging + busy timeouts for concurrent bot/web reads and writes) or **PostgreSQL 16**.
4. **Unified Runner (`scripts/run_all.py`)**:
   - Production process supervisor that boots and manages both the Web Gateway and Telegram Bot concurrently inside a single container or server.

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.11+
- Telegram Bot Token from [@BotFather](https://t.me/BotFather)
- Telegram MTProto API credentials (`API_ID` and `API_HASH`) from [my.telegram.org](https://my.telegram.org)
- A private Telegram channel with your bot added as Administrator

### 2. Configure Environment

Copy the example environment file:
```bash
cp .env.example .env
```

Populate `.env` with your values:
```env
BOT_TOKEN=123456789:AA_YOUR_BOT_TOKEN_HERE
ADMIN_IDS=123456789
STORAGE_CHANNEL=-100YOUR_STORAGE_CHANNEL_ID
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_32_character_api_hash_here
DATABASE_URL=sqlite+aiosqlite:///filebot.db
HOST=0.0.0.0
PORT=8080
```

### 3. Local Development

Run both services together:
```bash
# Windows
.venv\Scripts\python.exe scripts/run_all.py

# Linux / macOS
python3 scripts/run_all.py
```

Or run services individually:
```bash
# Run web gateway on http://localhost:8080
python -m server.app

# In another terminal: Run Telegram bot
python -m bot
```

Open `http://localhost:8080` in your browser.

---

## 🐳 Production Deployment

### Option A: Docker Compose (Recommended for VPS / Dedicated Servers)

Run the full platform with a persistent volume:
```bash
docker compose up -d
```

- Web Gateway is mapped to `http://YOUR_SERVER_IP:8080`.
- SQLite database and Telethon session files are persisted in the `nakama_data` volume.
- The optional SubsPlease RSS ingest worker runs only when you opt in (it needs its
  own `SUB_BOT_TOKEN` as administrator of the storage channel):

  ```bash
  docker compose --profile ingest up -d
  ```

On Fly.io the unified runner starts that worker automatically whenever
`SUB_BOT_TOKEN` and `STORAGE_CHANNEL` are set.

### Option B: Fly.io Cloud Deployment (24/7 Serverless Container)

1. Install Fly CLI: [fly.io/docs/hands-on/install-flyctl/](https://fly.io/docs/hands-on/install-flyctl/)
2. Authenticate: `flyctl auth login`
3. Create the persistent volume (1GB):
   ```bash
   flyctl volumes create nakama_data --region iad --size 1
   ```
4. Set production secrets:
   ```bash
   flyctl secrets set \
     BOT_TOKEN="your_token" \
     ADMIN_IDS="your_admin_id" \
     STORAGE_CHANNEL="-100YOUR_STORAGE_CHANNEL_ID" \
     TELEGRAM_API_ID="your_api_id" \
     TELEGRAM_API_HASH="your_api_hash" \
      ADMIN_PANEL_SECRET="a_long_random_secret_for_the_admin_dashboard"
   ```
5. Deploy:
   ```bash
   flyctl deploy
   ```

Windows users can also run:
```bat
deploy_fly.bat
```

---

## 🛠️ Operational Maintenance & Vault Sync

When adding legacy files or existing database records to the storage channel:
```bash
python scripts/sync_vault.py
```
This script iterates through all records in `filebot.db` that lack a `channel_message_id`, forwards them to the storage channel, and stores their persistent message references.

---

## 🔒 Security Best Practices
- Keep `.env`, `filebot.db`, and `*.session` files strictly out of version control (enforced in `.gitignore`).
- Store MTProto session files on persistent volumes in production (`/data/streamer_bot.session`).
- Never run with hardcoded secrets or bypass Git secret scanning.
