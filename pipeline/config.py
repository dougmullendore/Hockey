"""Settings for the whole pipeline. Change things here, not in the other files."""

# Seasons the site covers, oldest first. A season is named by its two years,
# e.g. 20252026 is the 2025-26 season.
SEASONS = [20212022, 20222023, 20232024, 20242025, 20252026, 20262027]

# Seasons used to train the expected-goals model (the newest full seasons).
XG_TRAIN_SEASONS = [20212022, 20222023, 20232024, 20242025, 20252026]
# Season held out to test the model before the final fit.
XG_TEST_SEASON = 20252026
# Bump this to force the model to be retrained on the next run.
XG_MODEL_VERSION = "xg-v1"

# Game types: 2 = regular season, 3 = playoffs.
GAME_TYPES = {2: "regular", 3: "playoffs"}

# Games from the last few days are re-downloaded every night because the
# league issues stat corrections after the final horn.
REFRESH_DAYS = 3

# Be polite to the NHL's servers.
FETCH_THREADS = 6
FETCH_RETRIES = 6
USER_AGENT = "Mozilla/5.0 (compatible; hockey-stats-site/1.0)"

API_WEB = "https://api-web.nhle.com/v1"
API_STATS = "https://api.nhle.com/stats/rest/en"

# Rink geometry (feet). The goal line is 89 ft from centre ice.
GOAL_X = 89.0

SITE_NAME = "The Slot"
SITE_TAGLINE = "NHL expected goals, goalie and team analytics"
