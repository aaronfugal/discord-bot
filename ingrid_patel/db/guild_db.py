from pathlib import Path
import sqlite3
from ingrid_patel.settings import DATA_DIR


def get_guild_db_path(guild_id: int) -> Path:
    """
    Returns the filesystem path to this guild's SQLite DB.
    Does not open the DB.
    """
    return DATA_DIR / f"{guild_id}.db"

def ensure_guild_db(guild_id: int) -> None:
    """
    Ensures the guild DB file exists
    """
    db_path = get_guild_db_path(guild_id)
    db_path.parent.mkdir(parents=True, exist_ok=True)  # Ensure the data directory exists

    conn = sqlite3.connect(db_path)
    try:
        from ingrid_patel.db.schema import init_schema
        init_schema(conn)
    finally:
        conn.close()