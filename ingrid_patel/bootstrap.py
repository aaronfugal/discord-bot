# ingrid_patel/bootstrap.py loads environment variables from .env 

from __future__ import annotations 

from pathlib import Path 
from dotenv import load_dotenv # the only place we load the env so other modules can use it

def load_env() -> None: # Define a function that returns null. The function only loads the env

    repo_root = Path(__file__).resolve().parent.parent # set root project directory
    env_path = repo_root / ".env" # locate env
    load_dotenv(dotenv_path=env_path, override=False) # load the env file into environment variables and if it already exists don't replace it if the real .env is loaded
