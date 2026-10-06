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

# --- Game predictions and season simulation ------------------------------
# How fast team ratings forget: each game back counts this fraction of the next.
PRED_CHANCES_DECAY = 0.97       # expected-goal difference (steady, so it can move fast)
PRED_RESULTS_DECAY = 0.995      # goals beyond expected (noisy, so it moves slowly)
# Games of "average team" mixed in before a rating is trusted.
PRED_CHANCES_PRIOR = 20.0
PRED_RESULTS_PRIOR = 80.0
# Share of a rating's weight kept over the summer.
PRED_SUMMER_FADE = 0.5
# ...and how much of its distance from average a team keeps over the summer.
PRED_SUMMER_REGRESS = 0.8
# Doubt about each team's true strength in the season simulation (logit units).
PRED_STRENGTH_DOUBT = 0.25
PRED_SIMULATIONS = 10000

# --- Money ------------------------------------------------------------------
# Salary cap ceiling and league-minimum salary by season, in millions of US
# dollars. Add a line when the league announces a new season's numbers; until
# then the newest line is reused.
SALARY_CAP = {
    20212022: (81.5, 0.75), 20222023: (82.5, 0.75), 20232024: (83.5, 0.775),
    20242025: (88.0, 0.775), 20252026: (95.5, 0.775), 20262027: (104.0, 0.85),
}
CAP_SPEND_SHARE = 0.95      # teams spend about this much of the ceiling on average
ROSTER_SPOTS = 23

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

# The companion newsletter. Its newest post titles are shown on the home page
# and it gets a link in the menu. Set NEWSLETTER_URL to "" to remove both.
NEWSLETTER_NAME = "Stars Spotlight"
NEWSLETTER_URL = "https://starsspotlight.substack.com"
SITE_TAGLINE = "NHL expected goals, goalie and team analytics"
