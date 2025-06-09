#!/usr/bin/env python3
"""
games_db_init.py

Creates and populates games.db for Ingrid Patel Discord Bot from a games.csv file.

Usage:
    python games_db_init.py --csv /path/to/games.csv --db /path/to/games.db
"""

import sqlite3
import csv
import ast
import os
import argparse

parser = argparse.ArgumentParser(description='Create and populate games.db from a CSV.')
parser.add_argument('--csv', default='games.csv', help='Path to the games CSV file')
parser.add_argument('--db', default='games.db', help='Path to the output SQLite database')
args = parser.parse_args()

csv_path = os.path.abspath(args.csv)
database_path = os.path.abspath(args.db)

if not os.path.exists(csv_path):
    print(f"CSV file does not exist: {csv_path}")
    exit(1)

try:
    conn = sqlite3.connect(database_path)
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS games (
        appID INTEGER PRIMARY KEY,
        name TEXT,
        release_date TEXT,
        estimated_owners TEXT,
        peak_ccu INTEGER,
        required_age INTEGER,
        price REAL,
        discount REAL,
        dlc_count INTEGER,
        about_the_game TEXT,
        supported_languages TEXT,
        full_audio_languages TEXT,
        reviews TEXT,
        header_image TEXT,
        website TEXT,
        support_url TEXT,
        support_email TEXT,
        windows BOOLEAN,
        mac BOOLEAN,
        linux BOOLEAN,
        metacritic_score INTEGER,
        metacritic_url TEXT,
        user_score INTEGER,
        positive INTEGER,
        negative INTEGER,
        score_rank TEXT,
        achievements INTEGER,
        recommendations INTEGER,
        notes TEXT,
        average_playtime_forever INTEGER,
        average_playtime_2weeks INTEGER,
        median_playtime_forever INTEGER,
        median_playtime_2weeks INTEGER,
        developers TEXT,
        publishers TEXT,
        categories TEXT,
        genres TEXT,
        tags TEXT,
        screenshots TEXT,
        movies TEXT
    )
    ''')

    rowcount = 0
    with open(csv_path, 'r', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            try:
                row = {key: (value if value is not None else '') for key, value in row.items()}
                row['appID'] = int(row.get('AppID', 0) or 0)
                row['name'] = row.get('Name', '')
                row['release_date'] = row.get('Release date', '')
                row['estimated_owners'] = row.get('Estimated owners', '')
                row['peak_ccu'] = int(row.get('Peak CCU', 0) or 0)
                row['required_age'] = int(row.get('Required age', 0) or 0)
                row['price'] = float(row.get('Price', 0.0) or 0.0)
                row['discount'] = float(row.get('Discount', 0.0) or 0.0)
                row['dlc_count'] = int(row.get('DLC count', 0) or 0)
                row['about_the_game'] = row.get('About the game', '')
                row['supported_languages'] = row.get('Supported languages', '')
                row['full_audio_languages'] = row.get('Full audio languages', '')
                row['reviews'] = row.get('Reviews', '')
                row['header_image'] = row.get('Header image', '')
                row['website'] = row.get('Website', '')
                row['support_url'] = row.get('Support url', '')
                row['support_email'] = row.get('Support email', '')
                row['windows'] = row.get('Windows', 'False').lower() in ('true', '1', 'yes')
                row['mac'] = row.get('Mac', 'False').lower() in ('true', '1', 'yes')
                row['linux'] = row.get('Linux', 'False').lower() in ('true', '1', 'yes')
                row['metacritic_score'] = int(row.get('Metacritic score', 0) or 0)
                row['metacritic_url'] = row.get('Metacritic url', '')
                row['user_score'] = int(row.get('User score', 0) or 0)
                row['positive'] = int(row.get('Positive', 0) or 0)
                row['negative'] = int(row.get('Negative', 0) or 0)
                row['score_rank'] = row.get('Score rank', '')
                try:
                    achievements_value = row.get('Achievements', '0')
                    if isinstance(achievements_value, str) and achievements_value.startswith("{"):
                        achievements_dict = ast.literal_eval(achievements_value)
                        row['achievements'] = achievements_dict.get('total', 0)
                    else:
                        row['achievements'] = int(achievements_value or 0)
                except (ValueError, SyntaxError):
                    row['achievements'] = 0
                row['recommendations'] = int(row.get('Recommendations', 0) or 0)
                row['notes'] = row.get('Notes', '')
                row['average_playtime_forever'] = int(row.get('Average playtime forever', 0) or 0)
                row['average_playtime_2weeks'] = int(row.get('Average playtime two weeks', 0) or 0)
                row['median_playtime_forever'] = int(row.get('Median playtime forever', 0) or 0)
                row['median_playtime_2weeks'] = int(row.get('Median playtime two weeks', 0) or 0)
                row['developers'] = row.get('Developers', '')
                row['publishers'] = row.get('Publishers', '')
                row['categories'] = row.get('Categories', '')
                row['genres'] = row.get('Genres', '')
                row['tags'] = row.get('Tags', '')
                row['screenshots'] = row.get('Screenshots', '')
                row['movies'] = row.get('Movies', '')
                
                cursor.execute('''
                    INSERT OR REPLACE INTO games (
                        appID, name, release_date, estimated_owners, peak_ccu, required_age,
                        price, discount, dlc_count, about_the_game, supported_languages, full_audio_languages,
                        reviews, header_image, website, support_url, support_email, windows, mac, linux,
                        metacritic_score, metacritic_url, user_score, positive, negative, score_rank,
                        achievements, recommendations, notes, average_playtime_forever,
                        average_playtime_2weeks, median_playtime_forever, median_playtime_2weeks,
                        developers, publishers, categories, genres, tags, screenshots, movies
                    ) VALUES (
                        :appID, :name, :release_date, :estimated_owners, :peak_ccu, :required_age,
                        :price, :discount, :dlc_count, :about_the_game, :supported_languages, :full_audio_languages,
                        :reviews, :header_image, :website, :support_url, :support_email, :windows, :mac, :linux,
                        :metacritic_score, :metacritic_url, :user_score, :positive, :negative, :score_rank,
                        :achievements, :recommendations, :notes, :average_playtime_forever,
                        :average_playtime_2weeks, :median_playtime_forever, :median_playtime_2weeks,
                        :developers, :publishers, :categories, :genres, :tags, :screenshots, :movies
                    )
                ''', row)
                rowcount += 1
            except Exception as e:
                print(f"Failed to process row: {e}")

    conn.commit()
    conn.close()
    print(f"Successfully imported {rowcount} games into {database_path}")

except sqlite3.OperationalError as e:
    print(f"SQLite OperationalError: {e}")
except Exception as e:
    print(f"Exception: {e}")
