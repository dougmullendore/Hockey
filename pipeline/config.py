"""Every setting in one place."""

SITE_NAME = "GOAT Hockey"
LEAGUE = "NHL"

# The NHL's public feed (the one nhl.com itself uses).
API = "https://api-web.nhle.com/v1/"
GAME_PAGE = "https://www.nhl.com/gamecenter/"   # followed by the game's number
PLAYER_PAGE = "https://www.nhl.com/player/"

# A season is named by the year it starts in. Its games are looked for from
# mid-September (the schedule's own regular-season start date decides what
# counts) to the end of June. Before SEASON_FLIP (month, day) the newest
# season is still last year's.
SEASON_FLIP = (9, 1)
SEASON_WEEKS_FROM = (9, 15)
SEASON_WEEKS_TO = (6, 30)
GAME_TYPES = (2, 3)           # 2 = regular season, 3 = playoffs; the preseason and all-star games are left out
STATS_GAME_TYPES = (2,)       # player and team stats count the regular season only

# Box scores this recent are fetched again: the league sends in corrections.
BOX_REFRESH_DAYS = 2
# Rosters (names, photos, height, weight, birthplace) are read again after this many days.
ROSTER_REFRESH_DAYS = 1

# Team logos and player photos are not stored here: the page shows them
# straight from the NHL's own site. Set either to "" to show none.
LOGO_URL = "https://assets.nhle.com/logos/nhl/svg/{team}_light.svg"
SHOW_PHOTOS = True

# Odds: each team's chance of winning, from this site's own ratings (see
# pipeline/odds.py). These settings were chosen by testing on 2021-22 to
# 2025-26 results.
ODDS_STEP = 0.01          # how far a rating moves per surprising goal, early in the season
ODDS_SETTLE = 20          # after about this many games the moves get smaller
ODDS_MIN_STEP = 0.005     # and never smaller than this
ODDS_KEEP = 0.8           # share of last season's rating a team starts with
ODDS_HOME = 0.07          # home ice, in the same units as a rating
ODDS_STRETCH = 2.0        # turns an expected share of the goals into a chance of winning
ODDS_MARGIN_CAP = 4       # a win by more than this many goals counts as this many
ODDS_TESTED = {"games": 5592, "favorite_won": 0.580, "home_won": 0.535, "seasons": "2022-23 to 2025-26",
               "given": "60 to 70%", "won": 0.65}

# The GOAT ranking (pipeline/goat.py) of the 32 teams: head to head first,
# then strength of schedule, the standings and record, in that order.
GOAT_WEIGHTS = (0.5, 0.3, 0.2)   # strength of schedule, place in the standings, record
GOAT_HEAD_TO_HEAD = 0.15  # a head-to-head lead outweighs a score gap up to this size (scores run 0 to 1)
GOAT_REACH = 40           # how far up or down the order one move can take a team

# Where to watch: the channels the league lists for each game. Networks in
# these countries are shown, national ones first.
WATCH_COUNTRIES = ("US", "CA")
WATCH_MAX = 4

# While a game is being played, the page itself re-reads ESPN's public
# scoreboard this often (in seconds) and shows the score as it changes. The
# NHL's own feed cannot be read by a web page, only by the job.
LIVE_SECONDS = 15
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?limit=100&dates="
# ESPN's short names for teams where they differ from the NHL's.
ESPN_ABBR = {"TB": "TBL", "SJ": "SJS", "LA": "LAK", "NJ": "NJD", "UTAH": "UTA", "VEG": "VGK", "WAS": "WSH", "MON": "MTL",
             "CLB": "CBJ", "NAS": "NSH", "WIN": "WPG", "CAL": "CGY", "FLO": "FLA"}

# Be polite to the servers.
FETCH_THREADS = 6
FETCH_RETRIES = 4
USER_AGENT = "Mozilla/5.0 (compatible; goat-hockey-stats-site/2.0; +https://github.com/dougmullendore/Hockey)"
