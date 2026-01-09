import sqlite3
from ingrid_patel.db.guild_db import get_guild_db_path, ensure_guild_db



def connect_guild_db(guild_id: int) -> sqlite3.Connection:
    ensure_guild_db(guild_id)
    db_path = get_guild_db_path(guild_id)
    conn = sqlite3.connect(db_path)
    return conn