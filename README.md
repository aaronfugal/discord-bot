# Ingrid Patel Discord Bot

> *A multipurpose Discord bot for game info, release reminders, and Plex integration.*

## Overview

**Ingrid Patel** is a Python-based Discord bot that fetches Steam game data, manages release reminders, and integrates with Plex via Radarr and Sonarr APIs. The bot uses an SQLite database of 73,000+ Steam games and offers robust user approval workflows and error handling.

## Features

- **Game Information:**  
  Fetch detailed info for any Steam game using public APIs.
- **Release Reminders:**  
  Set reminders for upcoming Steam releases. Daily scheduled checks notify users 24 hours before a game's release.
- **Plex Media Server Integration:**  
  Search, request, and queue movies or TV shows for Plex using Radarr/Sonarr (approved Discord users only).
- **User Approval Workflow:**  
  Approval requests tracked; users are auto-removed after 20 days of inactivity.
- **Extensible and Secure:**  
  Designed for easy expansion, robust error handling, and security via environment variables.

## Bot Commands

| Command                    | Description                                        |
|----------------------------|----------------------------------------------------|
| *search [game_name or AppID]* | Fetch details for a game from the database         |
| *appid [game name]*        | Return top 5 matching AppIDs from Steam            |
| *fetchgame [AppID]*        | Add a new game to the database manually            |
| *remindme [AppID]*         | Set a reminder for an upcoming game release        |
| *listreminders*            | List all upcoming game reminders                   |
| *plexmovie [movie ID]*     | Queue a movie to Plex (approved users only)        |
| *movieid [movie name]*     | Fetch TMDb movie IDs                               |
| *plexshow [show ID]*       | Queue a show to Plex (approved users only)         |
| *showid [show name]*       | Fetch TVDb show IDs                                |
| *all*                      | Show total games in the database                   |
| *patches*                  | Show current bot version and changelog             |
| *about*                    | Describe bot functionality and commands            |

## Technical Stack

- **Language:** Python 3.11+
- **Libraries:** `discord.py`, `requests`, `beautifulsoup4`, `sqlite3`, `python-dotenv`
- **Database:** SQLite (`games.db`, `upcoming.db`, `users.db`)
- **Containerization:** Deployed via Proxmox LXC container
- **Task Scheduling:** Asyncio for daily tasks

## Setup

1. **Clone this repo:**
    ```sh
    git clone https://github.com/yourusername/discord-bot.git
    cd discord-bot
    ```

2. **Install dependencies:**
    ```sh
    pip install -r requirements.txt
    ```

3. **Configure environment:**
    - Copy `.env.example` to `.env` and fill in your credentials.

4. **Create and populate the databases:**
    - Database initialization scripts are provided in `/tools/`.
    - Run the following commands (from repo root):
      ```sh
      python tools/games_db_init.py --csv games.csv --db games.db
      python tools/users_db_init.py --db users.db --admin_id <your_discord_id> --admin_username <your_username>
      python tools/upcoming_db_init.py --db upcoming.db
      ```
    - **Note:** You must provide a `games.csv` file with the correct columns. See `/tools/games.csv.example` for the required format.

5. **Run the bot:**
    ```sh
    python Ingrid-Patel/main.py
    ```


## Environment Variables (`.env`)

```env
DISCORD_TOKEN=your_discord_bot_token
STEAM_KEY=your_steam_api_key
RADARR_BASE_URL=http://radarr.local:7878
RADARR_API_KEY=your_radarr_api_key
RADARR_ROOT_FOLDER=M:\media\Movies
SONARR_BASE_URL=http://sonarr.local:8989
SONARR_API_KEY=your_sonarr_api_key
SONARR_ROOT_FOLDER=M:\media\Shows
