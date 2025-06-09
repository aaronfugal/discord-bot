import sqlite3
from datetime import datetime

DB_PATH = 'users.db'

def create_approved_users_table():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS approved_users (
            discord_id TEXT PRIMARY KEY,
            username TEXT,
            is_admin INTEGER DEFAULT 0,
            last_active TEXT
        )
    ''')
    conn.commit()
    conn.close()
    print("Table 'approved_users' created (if it didn't exist).")

def add_admin(discord_id, username):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute('''
        INSERT OR REPLACE INTO approved_users (discord_id, username, is_admin, last_active)
        VALUES (?, ?, ?, ?)
    ''', (discord_id, username, 1, now))
    conn.commit()
    conn.close()
    print(f"Admin user {username} (ID: {discord_id}) added.")

if __name__ == '__main__':
    create_approved_users_table()
    admin_discord_id = "555261159452966928" # My Discord ID
    admin_username = "fungaljungal"
    add_admin(admin_discord_id, admin_username)
    print("Database initialized and admin added.")
