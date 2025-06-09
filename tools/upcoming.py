#!/usr/bin/env python3
"""
upcoming_db.py

Initializes upcoming.db for Ingrid Patel Discord Bot, creating the upcoming_games table.

Usage:
    python upcoming_db_init.py [--db upcoming.db]

Default:
    --db upcoming.db
"""

import sqlite3
import argparse
import os

parser = argparse.ArgumentParser(description='Initialize upcoming.db and create upcoming_games table.')
parser.add_argument('--db', default='upcoming.db', help='Path to the upcoming.db file')
args = parser.parse_args()

DB_PATH = os.path.abspath(args.db)

def create_upcoming_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS upcoming_games (
        appID INTEGER PRIMARY KEY,
        name TEXT,
        release_date TEXT
    )
    ''')
    conn.commit()
    conn.close()
    print(f"Table 'upcoming_games' created in {DB_PATH} (if it didn't exist).")

if __name__ == '__main__':
    create_upcoming_db()
    print("Database initialized.")
