#!/usr/bin/env python3
"""
users_db_init.py

Initializes users.db for Ingrid Patel Discord Bot, creates the approved_users table,
and adds an initial admin user.

Usage:
    python users_db_init.py [--db users.db] [--admin_id <ID>] [--admin_username <name>]

Defaults:
    --db users.db
    --admin_id 555261159452966928
    --admin_username fungaljungal
"""

import sqlite3
from datetime import datetime
import argparse
import os

parser = argparse.ArgumentParser(description='Initialize users.db and add an admin user.')
parser.add_argument('--db', default='users.db', help='Path to the users.db file')
parser.add_argument('--admin_id', default='555261159452966928', help='Discord ID of admin user')
parser.add_argument('--admin_username', default='fungaljungal', help='Username of admin user')
args = parser.parse_args()

DB_PATH = os.path.abspath(args.db)

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
    print(f"Table 'approved_users' created in {DB_PATH} (if it didn't exist).")

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
    add_admin(args.admin_id, args.admin_username)
    print("Database initialized and admin added.")
