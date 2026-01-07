# Temporary entrypoint for refactoring purposes.

from pathlib import Path # Cross-platform way to work with files
import runpy # Run Python code file in another location as if it were the main program

def main() -> None: # Standard convention for difining the main function in python
    repo_root = Path(__file__).resolve().parents[1] # repo_root to this file which is resolved to its absolute path and go up two parent directories
    legacy_main = repo_root / "Ingrid-Patel" / "main.py" # Define legacy_main as the path to the legacy main.py file
    runpy.run_path(legacy_main, run_name="__main__") # Run the legacy main.py file as if it were the main program


if __name__ == "__main__": # Standard boilerplate to call the main() function when the script is executed directly
    main() # Call the main function