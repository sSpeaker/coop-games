import os

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.environ.get("DB_PATH", os.path.join(DATA_DIR, "coop.db"))

# Platforms shown in the catalog: label -> (OpenCritic browse slug, Co-optimus system id)
PLATFORMS = {
    "PC": ("pc", 4),
    "PS4": ("ps4", 22),
    "PS5": ("ps5", 30),
    "Switch": ("switch", 28),
    "Switch 2": ("switch%202", 34),
}

# Hours between automatic updates; 0 disables the scheduler
UPDATE_INTERVAL_HOURS = float(os.environ.get("UPDATE_INTERVAL_HOURS", "168"))
# Run an update on start when the database is empty
UPDATE_ON_EMPTY_START = os.environ.get("UPDATE_ON_EMPTY_START", "1") == "1"

# Delays between requests, seconds
DELAY_OPENCRITIC = float(os.environ.get("DELAY_OPENCRITIC", "0.6"))
DELAY_COOPTIMUS = float(os.environ.get("DELAY_COOPTIMUS", "0.6"))
DELAY_PEGI = float(os.environ.get("DELAY_PEGI", "1.0"))
DELAY_STEAM = float(os.environ.get("DELAY_STEAM", "1.0"))
DELAY_METACRITIC = float(os.environ.get("DELAY_METACRITIC", "1.0"))
DELAY_NINTENDO = float(os.environ.get("DELAY_NINTENDO", "0.5"))
BACKOFF_429 = float(os.environ.get("BACKOFF_429", "60"))

# Re-fetch game pages of recent games (score, trailers) when older than this many days
REFRESH_RECENT_DAYS = int(os.environ.get("REFRESH_RECENT_DAYS", "120"))
REFRESH_EVERY_DAYS = int(os.environ.get("REFRESH_EVERY_DAYS", "7"))
# Stop the incremental OpenCritic catalog crawl after this many pages without new games
CATALOG_STOP_AFTER = int(os.environ.get("CATALOG_STOP_AFTER", "3"))

# curl_cffi browser fingerprint to impersonate ("" = plain httpx)
IMPERSONATE = os.environ.get("IMPERSONATE", "chrome")

USER_AGENT = os.environ.get(
    "USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
)
