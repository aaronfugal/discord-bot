import sqlite3
import os
import asyncio
from discord import Client, Intents
from dotenv import load_dotenv
import logging
from datetime import datetime, timedelta, timezone
import requests
import re
from bs4 import BeautifulSoup

# Path setup for cross-platform compatibility
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

GAMES_DB_PATH = os.path.join(BASE_DIR, 'games.db')
UPCOMING_DB_PATH = os.path.join(BASE_DIR, 'upcoming.db')
USERS_DB_PATH = os.path.join(BASE_DIR, 'users.db')
CHANGELOG_PATH = os.path.join(os.path.dirname(BASE_DIR), 'changelog.txt')


# Setup logging
logging.basicConfig(level=logging.INFO)

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

if not TOKEN:
    logging.error("DISCORD_TOKEN not found in environment variables.")
    exit(1)

# Create an Intents object and enable the necessary intents
intents = Intents.default()
intents.message_content = True

# Define the client with the intents
client = Client(intents=intents)

_http = requests.Session()

version = "5.3.1"  # Change this to the version you are working on whenever you modify the code and push to github

specific_channel_id = 1268026496027459715  # Testing channel is 1268026496027459715 and game-recs channel is 1213415936187568128

# Load Radarr API settings from .env (if not already loaded)
RADARR_BASE_URL = os.getenv('RADARR_BASE_URL')
RADARR_API_KEY = os.getenv('RADARR_API_KEY')
RADARR_ROOT_FOLDER = os.getenv('RADARR_ROOT_FOLDER', r"M:\media\Movies")
# Load Sonarr API settings from .env (if not already loaded)
SONARR_BASE_URL = os.getenv('SONARR_BASE_URL').strip()
SONARR_API_KEY = os.getenv('SONARR_API_KEY').strip()
SONARR_ROOT_FOLDER = os.getenv('SONARR_ROOT_FOLDER', r"M:\media\Shows").strip()


# Global variable to track a pending movie approval request.
pending_media_request = None


# STEP 1: BOT SETUP
@client.event
async def on_ready():
    if not hasattr(client, 'ready'):
        client.ready = True
        logging.info("Bot is ready!")
        logging.info("Scheduling daily task now...")
        # Start the daily scheduled task
        client.loop.create_task(schedule_daily_task())
        channel = client.get_channel(specific_channel_id)
        if channel:
            logging.info(f"Channel found: {channel.name}")
            online_message = "I am back online."
            chunks = chunk_message(online_message)
            for chunk in chunks:
                await channel.send(chunk)
            logging.info("Sent message: I am back online.")
        else:
            logging.warning("Channel not found on startup")
        logging.info(f'{client.user} is now running!')

# STEP 2: DEFINE FUNCTIONS

# Function to ensure any scraped text data is sanitized
def SanitizeText(text):
    if not text:
        return "not available"

    # Use BeautifulSoup to strip all HTML tags properly
    soup = BeautifulSoup(text, "html.parser")
    clean_text = soup.get_text(separator=" ")  # Extract text and keep spacing

    # Remove excessive spaces and newlines
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    
    return clean_text


# Function to check all the games that are scheduled for reminders
def list_scheduled_games():
    conn = sqlite3.connect(UPCOMING_DB_PATH)
    cursor = conn.cursor()
    query = "SELECT appID, name, release_date FROM upcoming_games"
    cursor.execute(query)
    games = cursor.fetchall()
    conn.close()
    return games # Return a list of game titles

# Function to check if a game is in the upcoming.db
def is_game_scheduled(app_id):
    conn = sqlite3.connect(UPCOMING_DB_PATH)
    cursor = conn.cursor()
    query = "SELECT 1 FROM upcoming_games WHERE appID = ?"
    cursor.execute(query, (app_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None


# Function to check for upcoming releases
async def check_upcoming_releases():
    try:
        conn = sqlite3.connect(UPCOMING_DB_PATH)
        cursor = conn.cursor()
        
        # Get current time (UTC) and time 24 hours from now
        now = datetime.now(timezone.utc)
        in_24_hours = now + timedelta(hours=24)

        logging.info(f"Current time: {now}")
        logging.info(f"Time 24 hours from now: {in_24_hours}")
        
        # Query for games releasing in the next 24 hours
        query = "SELECT * FROM upcoming_games WHERE release_date BETWEEN ? AND ?"
        params = (now.strftime('%Y-%m-%d %H:%M:%S'), in_24_hours.strftime('%Y-%m-%d %H:%M:%S'))
        cursor.execute(query, params)
        games = cursor.fetchall()
        logging.info(f"Games found: {games}")
        conn.close()

        # Send notification for each game and then remove it
        if games:
            channel = client.get_channel(specific_channel_id)
            if channel:
                for game in games:
                    appID, name, release_date = game
                    steam_url = generate_steam_url(appID)
                    formatted_date = datetime.strptime(release_date, "%Y-%m-%d %H:%M:%S").strftime("%B %d, %Y")
                    message = f"{name} is coming out on {formatted_date}. Check it out here: {steam_url}"
                    await channel.send(message)
                    logging.info(f"Sent message: {message}")

                    # Remove the game from upcoming_games to prevent duplicate notifications
                    try:
                        conn_del = sqlite3.connect(UPCOMING_DB_PATH)
                        cur_del = conn_del.cursor()
                        cur_del.execute("DELETE FROM upcoming_games WHERE appID = ?", (appID,))
                        conn_del.commit()
                        conn_del.close()
                        logging.info(f"Removed game {appID} from upcoming_games after notification.")
                    except sqlite3.Error as e:
                        logging.error(f"Database error while removing game {appID}: {e}")
            else:
                logging.warning("Channel not found when sending scheduled messages.")
        else:
            logging.info("No games found for release in the next 24 hours.")
    except sqlite3.Error as e:
        logging.error(f"Database error: {e}")
    except Exception as e:
        logging.error(f"Error checking upcoming releases: {e}")


# Function to remove expired games from upcoming database
def remove_expired_games():
    try:
        conn = sqlite3.connect(UPCOMING_DB_PATH)
        cursor = conn.cursor()
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        delete_query = "DELETE FROM upcoming_games WHERE release_date < ?"
        cursor.execute(delete_query, (now_str,))
        conn.commit()
        rows_deleted = cursor.rowcount
        conn.close()
        logging.info(f"Removed {rows_deleted} expired game(s) from upcoming.db.")
    except sqlite3.Error as e:
        logging.error(f"Database error while removing expired games: {e}")



# Function to convert Steam date data to a usable format
def convert_release_date(release_date):
    try:
        # Log the raw data for debugging.
        logging.info(f"Raw release_date data: {release_date}")

        # If release_date is a dict, try to use the 'date' key.
        if isinstance(release_date, dict):
            if 'date' in release_date and release_date['date']:
                release_date_str = release_date['date']
                try:
                    # First try the original format.
                    return datetime.strptime(release_date_str, '%b %d, %Y')
                except ValueError as e:
                    logging.error(f"Failed to parse '{release_date_str}' with format '%b %d, %Y': {e}")
                    try:
                        # Fallback to an ISO-like format.
                        return datetime.strptime(release_date_str, '%Y-%m-%d')
                    except ValueError as e2:
                        logging.error(f"Failed to parse '{release_date_str}' with format '%Y-%m-%d': {e2}")
                        return None
            else:
                logging.error("Release date dictionary is missing the 'date' key or it is empty.")
                return None

        # If release_date is a string, try parsing it directly.
        elif isinstance(release_date, str):
            try:
                return datetime.strptime(release_date, '%b %d, %Y')
            except ValueError as e:
                logging.error(f"Failed to parse release date string '{release_date}' with format '%b %d, %Y': {e}")
                try:
                    return datetime.strptime(release_date, '%Y-%m-%d')
                except ValueError as e2:
                    logging.error(f"Failed to parse release date string '{release_date}' with format '%Y-%m-%d': {e2}")
                    return None
        else:
            logging.error("release_date is neither a dict nor a string.")
            return None

    except Exception as e:
        logging.error(f"Exception in convert_release_date: {e}")
        return None


# Function to connect to upcoming.db
def add_game_to_upcoming_db(app_id, name, release_date):
    conn = sqlite3.connect(UPCOMING_DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
    INSERT OR REPLACE INTO upcoming_games (appID, name, release_date)
    VALUES (?, ?, ?)
    ''', (app_id, name, release_date.strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()

# Function to fetch game data for writing to upcoming.db
def fetch_game_data(app_id):
    api_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
    logging.info(f"Fetching data from URL: {api_url}")  # Log the API URL
    response = _http.get(api_url)
    logging.info(f"Response status code: {response.status_code}")  # Log the response status code
    if response.status_code == 200:
        data = response.json()
        logging.info(f"API response data: {data}")  # Log the full API response
        if str(app_id) in data and data[str(app_id)]['success']:
            game_data = data[str(app_id)]['data']
            logging.info(f"Raw release_date from API: {game_data.get('release_date', {})}")
            return {
                'appID': game_data['steam_appid'],
                'name': game_data['name'],
                'release_date': game_data.get('release_date', {})
            }
    else:
        logging.error(f"Failed to fetch data, status code: {response.status_code}")
    return None



# Function to convert SQL query results to a dictionary
def query_to_dict(cursor, query, params=()):
    cursor.execute(query, params)
    columns = [col[0] for col in cursor.description]
    rows = cursor.fetchall()
    return [dict(zip(columns, row)) for row in rows]

# Function to split up messages in chunks when output is too large
def chunk_message(message, chunk_size=2000):
    words = message.split(' ')
    chunks = []
    current_chunk = ""
    for word in words:
        if len(current_chunk) + len(word) + 1 <= chunk_size:
            current_chunk += (" " + word if current_chunk else word)
        else:
            chunks.append(current_chunk)
            current_chunk = word
    if current_chunk:
        chunks.append(current_chunk)
    return chunks

# Function to generate Steam URL
def generate_steam_url(appID):
    return f"https://store.steampowered.com/app/{appID}"

# Function to fetch a single game
async def fetch_single_game(app_id):
    api_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
    try:
        response = _http.get(api_url)
        data = response.json()

        if str(app_id) in data and data[str(app_id)]['success']:
            game_data = data[str(app_id)]['data']

            # Insert game data into the database
            insertion_result = insert_game_into_db(game_data)

            return insertion_result
        else:
            return "Failed to fetch game data. Invalid app ID or game not found."
    except Exception as e:
        logging.error(f"Error fetching game data: {e}")
        return "Failed to fetch game data. Please try again later."


# Function to scrape the upcoming games from Steam
async def scrape_upcoming_games():
    upcoming_url = "https://store.steampowered.com/search/?filter=comingsoon&ndl=1"

    try:
        response = _http.get(upcoming_url, timeout=10)
        if response.status_code != 200:
            logging.error(f"Failed to fetch upcoming page, status code: {response.status_code}")
            return
        soup = BeautifulSoup(response.text, 'html.parser')
        # Find all <a> tags with href containing '/app/'
        game_links = soup.find_all('a', href=re.compile(r'/app/'))
        app_ids = set()
        for link in game_links:
            href = link.get('href', '')
            m = re.search(r'/app/(\d+)', href)
            if m:
                app_ids.add(m.group(1))
        logging.info(f"Scrape upcoming: Found {len(app_ids)} upcoming app IDs.")
        # For each app ID, fetch the game data and add to games.db if valid
        for app_id in app_ids:
            # Use your fetch_game_data to get the raw data
            game_data = fetch_game_data(app_id)
            if game_data:
                release_date = convert_release_date(game_data['release_date'])
                if release_date and (datetime.now() <= release_date <= datetime.now() + timedelta(hours=24)):
                    # We call fetch_single_game which already inserts into games.db
                    result = await (fetch_single_game(app_id))
                    logging.info(f"Scrape upcoming: Added game with appID {app_id} to games.db: {result}")
                else:
                    logging.info(f"Scrape upcoming: Game {app_id} skipped due to invalid or past release date.")
            else:
                logging.warning(f"Scrape upcoming: Failed to fetch game data for appID {app_id}.")
    except Exception as e:
        logging.error(f"Scrape upcoming: Error in scrape_upcoming_games: {e}")


# Fucntion to repeat daily task
async def schedule_daily_task():
    try:
        while True:
            now = datetime.now()
            target_time = datetime.strptime("18:00:00", "%H:%M:%S").time()
            next_run = datetime.combine(now.date(), target_time)
            if now > next_run:
                next_run += timedelta(days=1)
            wait_time = (next_run - now).total_seconds()
            logging.info(f"Next run scheduled for: {next_run}")
            logging.info(f"Waiting for {wait_time} seconds before next run")
            await asyncio.sleep(wait_time)

            channel = client.get_channel(specific_channel_id)
            if channel:
                await update_approved_users_activity(channel, inactive_days=20)
            try:
                await check_upcoming_releases()
                remove_expired_games()
                await scrape_upcoming_games()
            except Exception as e:
                logging.error(f"Error during scheduled task: {e}")

            # Remove inactive users after the task
            remove_inactive_users(inactive_days=20)

    except Exception as e:
        logging.error(f"Schedule loop crashed: {e}")

# Function to fetch game attributes for writing directly to games.db
def insert_game_into_db(game_data):
    try:
        conn = sqlite3.connect(GAMES_DB_PATH)
        cursor = conn.cursor()

        def process_list_of_dicts(data):
            if isinstance(data, list):
                return ','.join([item['description'] if isinstance(item, dict) and 'description' in item else str(item) for item in data])
            return str(data)

        def process_release_date(data):
            if isinstance(data, dict) and 'date' in data:
                return data['date']
            return str(data)

        query = """
        INSERT OR REPLACE INTO games (
            appID, name, release_date, estimated_owners, peak_ccu, required_age, price, 
            discount, dlc_count, about_the_game, supported_languages, full_audio_languages, 
            reviews, header_image, website, support_url, support_email, windows, mac, linux, 
            metacritic_score, metacritic_url, user_score, positive, negative, score_rank, 
            achievements, recommendations, notes, average_playtime_forever, 
            average_playtime_2weeks, median_playtime_forever, median_playtime_2weeks, 
            developers, publishers, categories, genres, tags, screenshots, movies
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        values = (
            game_data.get('steam_appid', None), 
            game_data.get('name', ''), 
            process_release_date(game_data.get('release_date', '')), 
            None, 
            game_data.get('peak_ccu', 0), 
            game_data.get('required_age', 0), 
            game_data.get('price_overview', {}).get('final', 0) / 100 if game_data.get('price_overview') else 0, 
            game_data.get('price_overview', {}).get('discount_percent', 0) if game_data.get('price_overview') else 0, 
            len(game_data.get('dlc', [])), 
            # SANITIZE DESCRIPTION FIELDS:
            SanitizeText(game_data.get('about_the_game', '')), 
            # If you want to sanitize supported languages and full audio languages, you might leave those as-is:
            ','.join(game_data.get('supported_languages', '').split(',')), 
            ','.join(game_data.get('full_audio_languages', '').split(',')), 
            SanitizeText(game_data.get('reviews', '')), 
            game_data.get('header_image', ''), 
            game_data.get('website', ''), 
            game_data.get('support_url', ''), 
            game_data.get('support_email', ''), 
            game_data.get('platforms', {}).get('windows', False), 
            game_data.get('platforms', {}).get('mac', False), 
            game_data.get('platforms', {}).get('linux', False), 
            game_data.get('metacritic_score', 0), 
            game_data.get('metacritic_url', ''), 
            game_data.get('user_score', 0), 
            game_data.get('positive', 0), 
            game_data.get('negative', 0), 
            game_data.get('score_rank', ''), 
            game_data.get('achievements', {}).get('total', 0), 
            game_data.get('recommendations', {}).get('total', 0), 
            SanitizeText(game_data.get('notes', '')), 
            game_data.get('average_playtime_forever', 0), 
            game_data.get('average_playtime_2weeks', 0), 
            game_data.get('median_playtime_forever', 0), 
            game_data.get('median_playtime_2weeks', 0), 
            ','.join(game_data.get('developers', [])), 
            ','.join(game_data.get('publishers', [])), 
            process_list_of_dicts(game_data.get('categories', [])), 
            process_list_of_dicts(game_data.get('genres', [])), 
            process_list_of_dicts(game_data.get('tags', [])), 
            process_list_of_dicts(game_data.get('screenshots', [])), 
            process_list_of_dicts(game_data.get('movies', []))
        )

        # Print values for debugging
        logging.info("Values to be inserted into the database:")
        for i, val in enumerate(values):
            logging.info(f"Value {i+1}: {val} (type: {type(val)})")

        cursor.execute(query, values)
        conn.commit()
        conn.close()

        return "Game data successfully added to the games database."
    except sqlite3.Error as e:
        logging.error(f"Database error: {e}")
        return "Failed to insert game data into the database. Please try again later."

# Function to fetch app ID's
def get_app_ids(game_name):
    search_url = "https://store.steampowered.com/api/storesearch"
    params = {"term": game_name, "l": "english", "cc": "US"}  # Adjust parameters as needed
    response = _http.get(search_url, params=params)
    if response.status_code == 200:
        results = response.json().get('items', [])
        top_5_results = [(result['name'], result['id']) for result in results[:5]]  # Return the top 5 results with names and IDs
        return top_5_results
    return []

# Function to query database by id and format results
async def fetch_game_attributes_by_id(app_id):
    try:
        conn = sqlite3.connect(GAMES_DB_PATH)
        cursor = conn.cursor()
        
        query = "SELECT * FROM games WHERE appID = ?"
        params = (app_id,)
        games = query_to_dict(cursor, query, params)
        
        conn.close()

        excluded_attributes = [
            'peak_ccu', 'price', 'discount', 'supported_languages', 'full_audio_languages', 
            'reviews', 'header_image', 'website', 'support_email', 'user_score', 'score_rank', 
            'metacritic_url', 'tags', 'screenshots', 'movies', 'average_playtime_forever', 
            'average_playtime_2weeks', 'median_playtime_forever', 'median_playtime_2weeks', 
            'categories', 'support_url', 'recommendations', 'metacritic_score'
        ]

        if len(games) == 0:
            return f"No game found with App ID: {app_id}"
        elif len(games) == 1:
            game = games[0]
            steam_url = generate_steam_url(game['appID'])
            response = ""
            for attr, value in game.items():
                if attr == 'appID':
                    response += f"**App ID**: {value}\n"
                elif attr == 'release_date' and value:
                    try:
                        formatted_date = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%B %d, %Y")
                    except ValueError:
                        formatted_date = value  # If parsing fails, return the original value
                    response += f"**Release Date**: {formatted_date}\n"
                elif attr == 'dlc_count':
                    response += f"**DLC Count**: {value}\n"
                elif attr == 'windows':
                    response += f"**Windows**: {'available' if value else 'not available'}\n"
                elif attr == 'mac':
                    response += f"**Mac**: {'available' if value else 'not available'}\n"
                elif attr == 'linux':
                    response += f"**Linux**: {'available' if value else 'not available'}\n"
                elif attr == 'about_the_game':
                    sanitized_text = SanitizeText(value) if value else "not available"
                    response += f"**{attr.replace('_', ' ').title()}**: {sanitized_text}\n"

                elif attr not in excluded_attributes:
                    response += f"**{attr.replace('_', ' ').title()}**: {value if value else 'not available'}\n"
            response += f"\nSteam URL: {steam_url}"
            return response
        else:
            response = "Multiple games found:\n"
            for game in games:
                response += f"- {game['name']} (App ID: {game['appID']})\n"
            return response

    except sqlite3.Error as e:
        logging.error(f"Database error: {e}")
        return "Failed to connect to database. Please try again later."

# Function to query database by name and format the results
async def fetch_game_attributes_by_name(game_name):
    try:
        conn = sqlite3.connect(GAMES_DB_PATH)
        cursor = conn.cursor()
        
        query = "SELECT * FROM games WHERE name LIKE ?"
        params = (f'%{game_name}%',)
        games = query_to_dict(cursor, query, params)
        
        conn.close()
        
        excluded_attributes = [
            'peak_ccu', 'price', 'discount', 'supported_languages', 'full_audio_languages', 
            'reviews', 'header_image', 'website', 'support_email', 'user_score', 'score_rank', 
            'metacritic_url', 'tags', 'screenshots', 'movies', 'average_playtime_forever', 
            'average_playtime_2weeks', 'median_playtime_forever', 'median_playtime_2weeks', 
            'categories', 'support_url', 'recommendations', 'metacritic_score'
        ]

        if len(games) == 0:
            return f"No game found with name: {game_name}"
        elif len(games) == 1:
            game = games[0]
            steam_url = generate_steam_url(game['appID'])
            response = ""
            for attr, value in game.items():
                if attr == 'appID':
                    response += f"**App ID**: {value}\n"
                elif attr == 'release_date' and value:
                    try:
                        formatted_date = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%B %d, %Y")
                    except ValueError:
                        formatted_date = value  # If parsing fails, return the original value
                    response += f"**Release Date**: {formatted_date}\n"
                elif attr == 'dlc_count':
                    response += f"**DLC Count**: {value}\n"
                elif attr == 'windows':
                    response += f"**Windows**: {'available' if value else 'not available'}\n"
                elif attr == 'mac':
                    response += f"**Mac**: {'available' if value else 'not available'}\n"
                elif attr == 'linux':
                    response += f"**Linux**: {'available' if value else 'not available'}\n"
                elif attr == 'about_the_game':
                    sanitized_text = SanitizeText(value) if value else "not available"
                    response += f"**{attr.replace('_', ' ').title()}**: {sanitized_text}\n"
                elif attr not in excluded_attributes:
                    response += f"**{attr.replace('_', ' ').title()}**: {value if value else 'not available'}\n"
            response += f"\nSteam URL: {steam_url}"
            return response
        else:
            response = "Multiple games found:\n"
            for game in games:
                response += f"- {game['name']} (App ID: {game['appID']})\n"
            response += "\nPlease specify the game name exactly or use the app ID to search."
            return response

    except sqlite3.Error as e:
        logging.error(f"Database error: {e}")
        return "Failed to connect to database. Please try again later."


# Function to return total number of games
async def fetch_total_games():
    try:
        conn = sqlite3.connect(GAMES_DB_PATH)
        cursor = conn.cursor()
        
        query = "SELECT COUNT(*) FROM games"
        cursor.execute(query)
        total_games = cursor.fetchone()[0]
        
        conn.close()
        
        response = f"Total number of games in the database: {total_games}"
        return response
    except sqlite3.Error as e:
        logging.error(f"Database error: {e}")
        return "Failed to connect to database. Please try again later."
    

# ================= Sonarr & Radarr API Helper Functions =================


def create_approved_users_table():
    conn = sqlite3.connect(USERS_DB_PATH)
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

def add_or_update_user(discord_id, username, is_admin=0):
    conn = sqlite3.connect(USERS_DB_PATH)
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute('''
        INSERT OR REPLACE INTO approved_users (discord_id, username, is_admin, last_active)
        VALUES (?, ?, ?, ?)
    ''', (discord_id, username, is_admin, now))
    conn.commit()
    conn.close()

def is_user_admin(discord_id):
    conn = sqlite3.connect(USERS_DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT is_admin FROM approved_users WHERE discord_id = ?', (discord_id,))
    result = cursor.fetchone()
    conn.close()
    return (result is not None) and (result[0] == 1)


def is_user_approved(discord_id):
    conn = sqlite3.connect(USERS_DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT is_admin FROM approved_users WHERE discord_id = ?', (discord_id,))
    result = cursor.fetchone()
    conn.close()
    # If found, return True. (Optionally, you can return the is_admin flag if needed.)
    return result is not None

def update_user_activity(discord_id):
    conn = sqlite3.connect(USERS_DB_PATH)
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute('UPDATE approved_users SET last_active = ? WHERE discord_id = ?', (now, discord_id))
    conn.commit()
    conn.close()

def remove_inactive_users(inactive_days=20):
    cutoff = datetime.utcnow() - timedelta(days=inactive_days)
    cutoff_iso = cutoff.isoformat()
    conn = sqlite3.connect(USERS_DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM approved_users WHERE last_active < ? AND discord_id != ?', (cutoff_iso, "555261159452966928"))
    conn.commit()
    conn.close()

async def update_approved_users_activity(channel, inactive_days=20):
    conn = sqlite3.connect(USERS_DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT discord_id FROM approved_users')
    users = cursor.fetchall()
    conn.close()
    # Use timezone-aware datetime in UTC:
    now = datetime.now(timezone.utc)
    for (discord_id,) in users:
        if discord_id == "555261159452966928":
            update_user_activity(discord_id)
            continue
        last_active = None
        # Scan the last 250 messages in the channel
        async for msg in channel.history(limit=250):
            if str(msg.author.id) == discord_id:
                last_active = msg.created_at  # This is offset-aware
                break  # Use the most recent message
        if last_active:
            if (now - last_active).days >= inactive_days:
                # Remove inactive user
                conn = sqlite3.connect(USERS_DB_PATH)
                cursor = conn.cursor()
                cursor.execute('DELETE FROM approved_users WHERE discord_id = ?', (discord_id,))
                conn.commit()
                conn.close()
                logging.info(f"Removed inactive user {discord_id} (last active: {last_active}).")
            else:
                # Update their activity timestamp in the DB
                update_user_activity(discord_id)
        else:
            # No recent message found: remove the user
            conn = sqlite3.connect(USERS_DB_PATH)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM approved_users WHERE discord_id = ?', (discord_id,))
            conn.commit()
            conn.close()
            logging.info(f"Removed user {discord_id} due to no recent activity.")

# Initialize the approved users table on startup.
create_approved_users_table()

def prepare_sonarr_payload(lookup_data, root_folder, quality_profile_id=1):
    """
    Prepares the payload for adding a series to Sonarr based on lookup data.

    Args:
        lookup_data (dict): The series data obtained from Sonarr's /series/lookup endpoint.
        root_folder (str): The root folder path where the series will be stored.
        quality_profile_id (int): The ID of the quality profile to assign to the series.

    Returns:
        dict: The payload ready to be sent to Sonarr's /series endpoint.
    """
    # Set the necessary fields for adding the series
    lookup_data['qualityProfileId'] = quality_profile_id
    lookup_data['rootFolderPath'] = root_folder
    lookup_data['monitored'] = True
    lookup_data['seasonFolder'] = True
    lookup_data['addOptions'] = {
        "searchForMissingEpisodes": True,
        "searchForCutoffUnmetEpisodes": True
    }

    # Ensure all seasons are monitored
    if 'seasons' in lookup_data:
        for season in lookup_data['seasons']:
            season['monitored'] = True

    return lookup_data

def radarr_add_movie(movie_id):
    url = f"{RADARR_BASE_URL}/api/v3/movie"
    headers = {"Content-Type": "application/json", "X-Api-Key": RADARR_API_KEY}
    payload = {
        "tmdbId": movie_id,
        "monitored": True,
        "qualityProfileId": 2,  # Adjust as needed (1080p profile ID)
        "rootFolderPath": RADARR_ROOT_FOLDER, 
        "minimumAvailability": "released"
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.ok:
            logging.info(f"Movie with TMDb ID {movie_id} added to Plex download queue.")
            return response.json()
        else:
            try:
                error_data = response.json()
                # Handle list of errors
                if isinstance(error_data, list):
                    error_messages = [err.get('message', '').lower() for err in error_data if isinstance(err, dict)]
                    combined_message = " | ".join(error_messages)
                    logging.error(f"Radarr returned error(s): {combined_message}")
                    if any("already" in msg or "exists" in msg for msg in error_messages):
                        logging.info(f"Movie with TMDb ID {movie_id} is already monitored in Radarr.")
                        return {"error": "Movie already monitored in Plex download queue."}
                else:
                    error_message = error_data.get("message", "").lower()
                    logging.error(f"Radarr returned error: {error_message}")
                    if "already" in error_message or "exists" in error_message:
                        logging.info(f"Movie with TMDb ID {movie_id} is already monitored in Radarr.")
                        return {"error": "Movie already monitored in Plex download queue."}
            except Exception as e:
                logging.error(f"Error parsing Radarr error response: {e}")
            logging.error(f"Failed to add movie. Status code: {response.status_code}")
            return None
    except Exception as e:
        logging.error(f"Error adding movie to Radarr: {e}")
        return None



def sonarr_add_show(tvdb_id, root_folder, quality_profile_id=1, sonarr_api_url=SONARR_BASE_URL, api_key=SONARR_API_KEY):
    headers = {'X-Api-Key': api_key}

    # Step 1: Lookup the series
    lookup_url = f"{sonarr_api_url}/api/v3/series/lookup"
    params = {"term": f"tvdb:{tvdb_id}"}
    logging.info(f"Looking up show: {lookup_url}")
    logging.info(f"Using params: {params}")
    lookup_response = _http.get(lookup_url, headers=headers, params=params)

    if lookup_response.status_code != 200:
        raise Exception(f'Error looking up series: {lookup_response.status_code} - {lookup_response.text}')

    lookup_data = lookup_response.json()
    if not lookup_data:
        raise Exception('No series found with the provided TVDB ID.')

    series_data = lookup_data[0]

    # Step 2: Prepare payload
    payload = prepare_sonarr_payload(series_data, root_folder, quality_profile_id)

    # Step 3: Add the series (NO params, just headers)
    add_series_url = f"{sonarr_api_url}/api/v3/series"
    add_series_response = requests.post(add_series_url, json=payload, headers=headers)

    if add_series_response.status_code != 201:
        try:
            error_data = add_series_response.json()
            # Sonarr returns a list of errors when the series exists
            if isinstance(error_data, list):
                for err in error_data:
                    if err.get('errorCode') == 'SeriesExistsValidator':
                        return {"error": "Show already monitored in Plex download queue"}
                # fallback: join all messages
                combined = " | ".join(e.get('errorMessage', "") for e in error_data)
                return {"error": combined}
            # or a single-object error
            elif isinstance(error_data, dict) and "errorMessage" in error_data:
                return {"error": error_data["errorMessage"]}
        except Exception:
            pass

        logging.error(f"Failed to add show. Status code: {add_series_response.status_code}")
        return None


    return add_series_response.json()


    
def radarr_search_movies(search_term):
    url     = f"{RADARR_BASE_URL}/api/v3/movie/lookup"
    headers = {"X-Api-Key": RADARR_API_KEY}
    params  = {"term": search_term}

    logging.info(f"[RADARR] GET {url}  params={params}  headers={headers}")
    try:
        # send request with a 5s connect / 10s read timeout
        response = _http.get(url, headers=headers, params=params, timeout=(5, 10))
        # raise on any HTTP error status (4xx / 5xx)
        response.raise_for_status()

        movies = response.json()
        logging.info(f"[RADARR] ← {len(movies)} results")
        return movies

    except Exception:
        # logs full traceback so you can see exactly what went wrong
        logging.exception(f"[RADARR] lookup failed for term={search_term}")
        return None
    
def sonarr_search_shows(search_term):
    url     = f"{SONARR_BASE_URL}/api/v3/series/lookup"
    headers = {"X-Api-Key": SONARR_API_KEY}
    params  = {"term": search_term}

    logging.info(f"[SONARR] GET {url} params={params} headers={headers}")
    try:
        # add the same (connect, read) timeout tuple here:
        response = _http.get(
            url,
            headers=headers,
            params=params,
            timeout=(5, 10)
        )
        if response.ok:
            return response.json()
        else:
            logging.error(f"Sonarr search failed, status code: {response.status_code}")
            return None
    except Exception as e:
        logging.error(f"Error searching shows in Sonarr: {e}")
        return None



# STEP 3: MESSAGE LISTENER
@client.event
async def on_message(message):
    # Ignore messages sent by the bot itself
    if message.author == client.user:
        return

    # Check if the message is in the specific channel
    if message.channel.id != specific_channel_id:
        return

    content = message.content.lower()
    
    # Command to fetch game attributes and Steam URL
    if content.startswith("*search"):
        search_term = content[len("*search "):].strip()
        # If they gave us a bare AppID, force a DB-update first:
        if search_term.isdigit():
            app_id = int(search_term)
            # let them know you’re refreshing
            await message.channel.send("🔄 Fetching latest info…")
            # this will INSERT or REPLACE into games.db without sending its own output
            await fetch_single_game(app_id)

            # now read the fresh data out of the DB
            response = await fetch_game_attributes_by_id(app_id)
            if "No game found" in response:
                response += "\n\nMake sure the App ID is correct. You can use `*appid [game name]` to find the App ID."
        else:
            # first try to resolve by name
            response = await fetch_game_attributes_by_name(search_term)

            # if exactly one match, extract its ID and refresh it
            if not response.startswith("Multiple") and not response.startswith("No game"):
                # parse the AppID out of the response (or re-query the DB)
                m = re.search(r"\*\*App ID\*\*: (\d+)", response)
                if m:
                    app_id = int(m.group(1))
                    await message.channel.send("🔄 Fetching latest info…")
                    await fetch_single_game(app_id)
                    # and re-pull from DB (to leverage all your formatting code)
                    response = await fetch_game_attributes_by_id(app_id)
                #else leave the "Multiple games found" or "No game found" as is
            if "No game found" in response:
                response += "\n\nDouble-check the spelling or try `*appid [game name]` to find the correct App ID."
            elif "Multiple games found" in response:
                response += "\n\nUse `*search [exact name]` or `*search [App ID]` to get specific details."

        chunks = chunk_message(response)
        for chunk in chunks:
            await message.channel.send(chunk)

    # Command to fetch info about the bot 
    if content == "*about":
        response = (
            f"I return information about games on Steam and I can add movies to the download queue for Aaron's Plex server. Use \\* to get my attention.\n\n"
            f"I have a database of all the games currently released on steam and update the database daily with new games. I can also send reminders about games that you add to a reminders list. Approved users in the channel can also request downloads to be added to the plex media server. Contact Aaron for login credentials to Plex.\n\n"
            f"There are 10 commands I respond to:\n"
            f"- Use `*search [game_name]` or `*search [app ID]` to search for a game by its app ID or name and return information on it from the database. If multiple games are found, the app IDs will be listed.\n"
            f"- Use `*about` to find out what I can do.\n"
            f"- Use `*all` to see how many games are currently in the database.\n"
            f"- Use `*patches` to check my version and any new features.\n"
            f"- Use `*fetchgame [app ID]` to manually add a game to the database if it is not already there. You can add games that are not released yet. If the app ID is unknown, use the command below to find it.\n"
            f"- Use `*appid [game name]` to return the app ID from web results.\n"
            f"- Use `*remindme [app ID]` to add a game to the reminder list so that I can notify you when the game is released. Only games in the database can be added to the reminder list, so you'll need to add the game to the databse first using the *fetchgame command.\n"
            f"- Use `*listreminders` to list all games that are scheduled for reminders. \n"
            f"- Use `*plexmovie [movie ID]` to add a movie to the download queue for the Plex server. Only approved users can use this command. \n"
            f"- Use `*movieid [movie name]` to return the movie ID from web results. \n"
            f"- Use `*plexshow [show ID]` to add all seasons of a show to the download queue for the Plex server. Only approved users can use this command. \n"
            f"- Use `*showid [show name]` to return the show ID from web results. \n"

         )

        chunks = chunk_message(response)
        for chunk in chunks:
            await message.channel.send(chunk)

    # Command to display the number of games in the database
    if content == "*all":
        response = await fetch_total_games()
        chunks = chunk_message(response)
        for chunk in chunks:
            await message.channel.send(chunk)

    # Command to display the changelog
    if content == "*patches":
        try:
            with open(CHANGELOG_PATH, 'r') as file:
                response = file.read()
            chunks = chunk_message(response)
            for chunk in chunks:
                await message.channel.send(chunk)
        except FileNotFoundError:
            await message.channel.send("Changelog file not found.")
        except Exception as e:
            await message.channel.send(f"Error reading changelog: {e}")

    # Command to add a game to the database
    if content.startswith("*fetchgame"):
        app_id = content[len("*fetchgame "):].strip()
        response = await fetch_single_game(app_id)
        if "successfully added" in response:
            response += "\n\nYou can now use `*remindme [App ID]` if you'd like me to remind you when this game is released."
        elif "Failed to fetch game data" in response:
            response += "\n\nMake sure the App ID is valid. Use `*appid [game name]` if you're not sure."
        chunks = chunk_message(response)
        for chunk in chunks:
            await message.channel.send(chunk)


    # Command to display an app ID
    if content.startswith("*appid"):
        game_name = content[len("*appid "):].strip()
        app_ids = get_app_ids(game_name)
        if app_ids:
            response = "Top 5 search results:\n\n" + "\n".join(
                [f"- {name}: {app_id}" for name, app_id in app_ids]
            ) + "\n\nNext: Use `*fetchgame [app ID]` to add one of these games to the database!"
            await message.channel.send(response)
        else:
            await message.channel.send(
                f"Could not find any app IDs for '{game_name}'. Double-check the name and try again."
            )

    # Command to add a movie to Radarr (monitored) via *plex command
    if content.startswith("*plexmovie"):
        parts = content.split()
        if len(parts) < 2:
            await message.channel.send("Usage: *plexmovie [movie ID]")
            return
        try:
            movie_id = int(parts[1])
        except ValueError:
            await message.channel.send("Invalid movie ID. Please enter a numeric movie ID found from the *movieid command.")
            return
        
        user_id = str(message.author.id)
        
        # Check if there is a pending movie approval request
        global pending_media_request
        if pending_media_request is not None:
            await message.channel.send("There is already a pending approval request. Please wait until it is resolved.")
            return
        
        # Check if the user is approved
        if not is_user_approved(user_id):
            # Initiate admin approval workflow
            pending_media_request = {"user_id": user_id, "movie_id": movie_id, "channel": message.channel}
            await message.channel.send(f"User {message.author.name} is not approved. Approval from Aaron needed.")
            try:
                def approval_check(m):
                    return (m.content.strip() == "Approved" and 
                            is_user_admin(str(m.author.id)) and 
                            m.channel == message.channel)
                admin_response = await client.wait_for("message", timeout=20*60, check=approval_check)
                # If we got here, an admin has approved the request.
                add_or_update_user(user_id, message.author.name, is_admin=0)
                update_user_activity(user_id)
                result = radarr_add_movie(movie_id)
                if result:
                    await message.channel.send("User added to approval table and movie added to Plex download queue.")
                else:
                    await message.channel.send("Movie approval succeeded but failed to add movie to Plex download queue.")
            except asyncio.TimeoutError:
                await message.channel.send("Approval request timed out. Please try again later or contact Aaron directly.")
            finally:
                pending_media_request = None
            return
        else:
            # User is already approved; update activity and add movie.
            update_user_activity(user_id)
            try:
                result = radarr_add_movie(movie_id)
                if isinstance(result, dict) and result.get("error") == "Movie already monitored in Plex download queue":
                    await message.channel.send("That movie is already monitored in Plex download queue.")
                elif result:
                    await message.channel.send("Movie added to Plex download queue.")
                else:
                    await message.channel.send("Something went wrong while adding the movie. Ask Aaron to check the logs.")
            except Exception as e:
                logging.error(f"Unexpected error during movie addition: {e}")
                await message.channel.send("An error occurred. Ask Aaron to check the logs for details.")


    # Command to add a show to Sonarr (monitored) via *plexshow command.
    if content.startswith("*plexshow"):
        parts = content.split()
        if len(parts) < 2:
            await message.channel.send("Usage: *plexshow [show ID]")
            return
        try:
            show_id = int(parts[1])
        except ValueError:
            await message.channel.send("Invalid show ID. Please enter a numeric show ID found from the *showid command.")
            return
        
        user_id = str(message.author.id)
        
        if pending_media_request is not None:
            await message.channel.send("There is already a pending approval request. Please wait until it is resolved.")
            return
        
        if not is_user_approved(user_id):
            pending_media_request = {"user_id": user_id, "show_id": show_id, "channel": message.channel}
            await message.channel.send(f"User {message.author.name} is not approved. Approval from Aaron needed.")
            try:
                def approval_check(m):
                    return (m.content.strip() == "Approved" and 
                            is_user_admin(str(m.author.id)) and 
                            m.channel == message.channel)
                admin_response = await client.wait_for("message", timeout=20*60, check=approval_check)
                add_or_update_user(user_id, message.author.name, is_admin=0)
                update_user_activity(user_id)
                result = sonarr_add_show(show_id, SONARR_ROOT_FOLDER)
                if result:
                    await message.channel.send("User added to approval table and show added to Plex download queue.")
                else:
                    await message.channel.send("Show approval succeeded but failed to add show to Plex download queue.")
            except asyncio.TimeoutError:
                await message.channel.send("Approval request timed out. Please try again later or contact Aaron directly.")
            finally:
                pending_media_request = None
            return
        else:
            update_user_activity(user_id)
            try:
                result = sonarr_add_show(show_id, SONARR_ROOT_FOLDER)
                if isinstance(result, dict) and result.get("error") == "Show already monitored in Plex download queue":
                    await message.channel.send("That show is already monitored in Plex download queue.")
                elif result:
                    await message.channel.send("Show added to Plex download queue as monitored.")
                else:
                    await message.channel.send("Something went wrong while adding the show. Ask Aaron to check the logs.")
            except Exception as e:
                logging.error(f"Unexpected error during show addition: {e}")
                await message.channel.send("An error occurred. Ask Aaron to check the logs for details.")



    # Command to search for movies in Radarr and return their TMDb IDs.
    if content.startswith("*movieid"):
        search_term = content[len("*movieid "):].strip()
        if not search_term:
            await message.channel.send("Usage: *movieid [movie title]")
            return
        results = radarr_search_movies(search_term)
        if results:
            # Limit to top 5 results if there are more.
            top_results = results[:5]
            response_str = "Top movie search results:\n\n" + "\n".join(
                [f"- {movie['title']} ({movie['year']}) (Movie ID: {movie['tmdbId']})" for movie in top_results]
            ) + "\n\nNow use the *plexmovie [movie ID] command to add a movie to the Plex download queue."

            await message.channel.send(response_str)
        else:
            await message.channel.send("No movies found or an error occurred during search.")

        # Command to search for shows in Sonarr and return their TVDB IDs.
    if content.startswith("*showid"):
        search_term = content[len("*showid "):].strip()
        if not search_term:
            await message.channel.send("Usage: *showid [show title]")
            return
        results = sonarr_search_shows(search_term)
        if results:
            # Limit to top 5 results if there are more.
            top_results = results[:5]
            response_str = "Top show search results:\n\n" + "\n".join(
                [f"- {show['title']} ({show.get('year', 'N/A')}) (Show ID: {show['tvdbId']})" for show in top_results]
            ) + "\n\nNow use the *plexshow [show ID] command to add a show to Plex download queue."
            await message.channel.send(response_str)
        else:
            await message.channel.send("No shows found or an error occurred during search.")


    # Command to list reminders and add a game to reminder list
    if content == "*listreminders":
        games = list_scheduled_games()
        if games:
            sorted_games = sorted(games, key=lambda game: datetime.strptime(game[2], '%Y-%m-%d %H:%M:%S'))
            response = "Games Scheduled for Reminders:\n" + "\n".join(
                [f"- {game[1]} (Release Date: {datetime.strptime(game[2], '%Y-%m-%d %H:%M:%S').strftime('%B %d, %Y')})" for game in sorted_games]
            )
            chunks = chunk_message(response)
            for chunk in chunks:
                await message.channel.send(chunk)
        else:
            await message.channel.send("No games are currently scheduled for reminders.")
    elif content.startswith("*remindme"):
        app_id = content[len("*remindme "):].strip()
        try:
            app_id = int(app_id)
        except ValueError:
            await message.channel.send("Invalid App ID. Please enter a valid integer. Use `*appid [game name]` to find the App ID.")
            return

        if is_game_scheduled(app_id):
            await message.channel.send("Game is already scheduled for a reminder. You can check all reminders with `*listreminders`.")
            return

        game_data = fetch_game_data(app_id)
        if game_data:
            release_date = convert_release_date(game_data['release_date'])
            if release_date and (release_date > datetime.now() or game_data['release_date'].get('coming_soon')):
                add_game_to_upcoming_db(game_data['appID'], game_data['name'], release_date)
                formatted_date = release_date.strftime('%B %d, %Y')
                await message.channel.send(
                    f"Game '{game_data['name']}' added to the reminder list! I will remind you 24 hours before {formatted_date}.\n\nYou can view all scheduled reminders anytime with `*listreminders`."
                )
            else:
                await message.channel.send("The game is not upcoming or does not have a valid release date.")
                logging.error("The game is not upcoming or does not have a valid release date.")
        else:
            await message.channel.send("Failed to fetch game data. Double-check the App ID or use `*appid [game name]` to find it.")
            logging.error("Failed to fetch game data.")



# STEP 4: MAIN ENTRY POINT
if __name__ == '__main__':
    import signal

    # grab the bot’s loop
    loop = asyncio.get_event_loop()

    # schedule client.close() on SIGINT/SIGTERM
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(client.close()))
        except NotImplementedError:
            pass

    # now run as usual
    client.run(TOKEN)
