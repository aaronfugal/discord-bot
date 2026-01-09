from pathlib import Path
import os
from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()

# Paths
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "guilds"

# Discord
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Timezone
TIMEZONE = "America/Denver" # Mountain Time Zone (all servers)

# Scheduler
REMINDER_LOOKAHEAD_HOURS = 24 # Look ahead this many hours for reminders to send