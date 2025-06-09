import sqlite3

def create_upcoming_db():
    db_path = 'upcoming.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create the upcoming_games table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS upcoming_games (
        appID INTEGER PRIMARY KEY,
        name TEXT,
        release_date TEXT
    )
    ''')

    conn.commit()
    conn.close()

if __name__ == '__main__':
    create_upcoming_db()
