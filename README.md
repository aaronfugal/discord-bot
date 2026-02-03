# Ingrid Patel Discord Bot

> A multipurpose Discord bot for Steam game info, release reminders, and Plex automation via Radarr/Sonarr.

## Overview

**Ingrid Patel** is a Python Discord bot that:
- fetches Steam game data (search + details),
- manages release reminders (scheduled checks),
- integrates with a Plex stack via **Radarr** and **Sonarr**,
- supports per-server (guild) configuration and approval workflows.

State is stored in SQLite (multiple DB files). The bot is designed to run unattended (systemd service / container / VM) and be easy to extend.

---

## Features

- **Steam Game Info**
  - Search by name or AppID.
  - Pull details using Steam + stored metadata.

- **Release Reminders**
  - Users can subscribe to reminders for upcoming releases.
  - Scheduled jobs check upcoming releases and notify users.

- **Plex Automation (Radarr/Sonarr)**
  - Lookup IDs (TMDb/TVDb workflows).
  - Request movies/shows through Radarr/Sonarr.
  - Protected by an approval system (only approved Discord users can request media).

- **Approval Workflow**
  - Track approvals / requests.
  - Optional cleanup for stale approvals/users (depending on configuration).

- **Production-Friendly**
  - Environment-variable configuration.
  - Robust API error handling and logging.
  - Structured code layout for long-term growth.

---

## Commands

> Command names reflect the bot’s intent; actual command set may depend on enabled modules / configuration.

| Command | Description |
|---|---|
| `*search <game name or appid>` | Search games or fetch details for a specific AppID |
| `*remindme <appid>` | Create a reminder for a game release |
| `*listreminders` | List reminders currently configured |
| `*movieid <movie name>` | Find movie IDs for Radarr (TMDb) |
| `*plexmovie <tmdb id>` | Add a movie to Radarr (approved users only) |
| `*showid <show name>` | Find show IDs for Sonarr (TVDb) |
| `*plexshow <tvdb id>` | Add a show to Sonarr (approved users only) |
| `*help` | Show available commands / usage |

---

## Tech Stack

- **Python:** 3.11+ (works with newer versions as well)
- **Discord Library:** `discord.py`
- **HTTP:** `aiohttp`
- **Database:** SQLite
- **Scheduling:** asyncio-based scheduler/services
- **Media Integration:** Radarr + Sonarr APIs

---

## Project Layout (Refactor)

```text
ingrid_patel/
  app.py
  bootstrap.py
  settings.py
  settings_media.py
  clients/
  commands/
  db/
  services/
  utils/
requirements.txt
.env.example
```

---

## Setup (Local Dev)

1. **Clone**
   ```bash
   git clone https://github.com/aaronfugal/discord-bot.git
   cd discord-bot
   ```

2. **Create venv + install**
   ```bash
   python -m venv .venv
   # Windows:
   .\.venv\Scripts\activate
   # Linux/macOS:
   source .venv/bin/activate

   pip install -r requirements.txt
   ```

3. **Configure**
   ```bash
   cp .env.example .env
   ```
   Fill out the variables in `.env`.

4. **Run**
   ```bash
   python -m ingrid_patel
   ```

---

## Setup (Production / systemd)

Typical systemd service flow:
- Install code in a stable directory (example: `/root/Discord-Bot/Ingrid-Patel`)
- Use a dedicated venv (example: `/root/Discord-Bot/venv`)
- Run via module entrypoint:

```ini
ExecStart=/root/Discord-Bot/venv/bin/python3 -m ingrid_patel
WorkingDirectory=/root/Discord-Bot/Ingrid-Patel
EnvironmentFile=-/root/Discord-Bot/Ingrid-Patel/.env
Restart=always
```

> If your service still points to `main.py`, update it to `-m ingrid_patel` after you deploy the refactor.

---

## Environment Variables (`.env`)

Example:

```env
# Discord
DISCORD_TOKEN=your_discord_bot_token

# Steam (if used)
STEAM_KEY=your_steam_api_key

# Radarr
RADARR_BASE_URL=http://radarr.local:7878
RADARR_API_KEY=your_radarr_api_key
RADARR_ROOT_FOLDER=/path/to/movies

# Sonarr
SONARR_BASE_URL=http://sonarr.local:8989
SONARR_API_KEY=your_sonarr_api_key
SONARR_ROOT_FOLDER=/path/to/tv
```

> **Note:** Root folder paths must match what Radarr/Sonarr can see from their host environment.

---

## Databases / “Factory Reset”

The bot uses SQLite files for state (exact filenames depend on configuration).

For a clean install:
1. stop the service
2. delete the SQLite DB files in the bot directory (or `data/` directory if you store them there)
3. restart the service so the bot re-initializes tables

Example:
```bash
sudo systemctl stop Discord-Bot.service
sudo rm -f /root/Discord-Bot/Ingrid-Patel/*.db
sudo rm -f /root/Discord-Bot/Ingrid-Patel/data/*.db
sudo systemctl start Discord-Bot.service
```

---

## Security Notes

- Never commit `.env` (contains secrets).
- Prefer least-privilege tokens and restrict Radarr/Sonarr access to trusted networks.
- If hosting publicly, lock down endpoints (VPN / firewall / access policies).

---

## License

See `LICENSE`.
