"""Settings for the whole pipeline. Change things here, not in the other files."""

import datetime as _dt

# The first season the site covers. A season is named by its two years,
# e.g. 20252026 is the 2025-26 season.
FIRST_SEASON = 20212022


def _seasons_through_today() -> list[int]:
    today = _dt.datetime.now(_dt.timezone.utc).date()
    last_start = today.year if today.month >= 9 else today.year - 1
    first_start = FIRST_SEASON // 10000
    return [y * 10000 + y + 1 for y in range(first_start, last_start + 1)]


# Every season from FIRST_SEASON to the current one, oldest first. A new
# season is picked up automatically each September.
SEASONS = _seasons_through_today()

# The expected-goals model is trained on this many of the newest completed
# seasons, and retrains itself whenever another season finishes.
XG_TRAIN_SEASON_COUNT = 5
# Bump this to force the model to be retrained on the next run.
XG_MODEL_VERSION = "xg-v3"
# How the league's scorers record shots drifts from year to year, so recent
# seasons count for more: each season back is worth this fraction of the next.
XG_SEASON_DECAY = 0.5
# While a season is young its xG is scaled toward last season's level; this
# is how many expected goals of "benefit of the doubt" last season gets.
XG_SCALE_PRIOR = 1500.0

# --- WAR ---------------------------------------------------------------
# Pull toward the prior, in hours of ice time (chosen by cross-validation).
WAR_LAMBDA_EV = 20.0
WAR_LAMBDA_PP = 5.0
# A skater's rating starts each season at this fraction of last season's.
WAR_PRIOR_FADE = 0.7
# Finishing credit: goals above expected are multiplied by xG / (xG + K).
WAR_FINISHING_K = 20.0
# Fallback until there is a full season to measure it from.
WAR_GOALS_PER_WIN = 6.0

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

SITE_NAME = "GOAT Hockey"
SITE_TAGLINE = "NHL expected goals, goalie and team analytics"
