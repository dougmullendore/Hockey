# GOAT Hockey

Every NHL game, week by week, with each team's chance of winning, where to
watch and the score as it happens; the standings and a GOAT ranking of the 32
teams; team and player stats; and a page for every team, game and player.

It is the hockey version of the volleyball site
(github.com/dougmullendore/Volleyball) and works the same way.

You do not need to run anything. GitHub does it all on a schedule.

## What the site shows

- **Games** (first page): every game this week, grouped by day. Games still to
  come show the start time in the reader's own time zone, each team's chance
  of winning and where to watch; finished ones show the score (with OT or SO
  when it went past regulation) and link to the box score. Buttons step to
  earlier and later weeks, and a menu narrows the list to one team's whole
  season. The number beside each team is its place in the league standings.
- **Standings** (second page): the league's own table, by division, as the
  wild-card playoff picture, by conference or for the whole league, plus the
  site's own GOAT ranking.
- **Teams** (third page): a sortable table of every team's stats per game.
- **Players** (fourth page): every regular ranked by Impact per game; each
  name opens a card with his percentiles.

## Lines

The **Lines** page (fifth page, `#/lines/DAL`) shows a team's line
combinations: four forward lines (left wing, center, right wing), three
defense pairs, the two power-play units, the two penalty-kill units and the
goalies, each player with his photo and a link to his card.

Nobody announces these to the site: they are worked out from the league's
shift charts, which list every shift of every game (`pipeline/lines.py`).

- The three forwards who spent the most five-on-five time together in the
  team's last game are a line, then the next three among the rest, and so on;
  defense pairs the same way. Lines are numbered by ice time together, and
  each shows that time and how long the same players have been together over
  the season.
- Power-play and penalty-kill units are the groups out together most over
  the last three games (one game has too little of either to go on).
- The goalie who started the last game is first, then the others on the roster.
- It shows what the coach did, not what he plans: a line broken up during
  the game, an injury or a benching shows as it happened. Left and right
  sides go by each player's listed position and shooting hand.
- There is no injury list: the league's feed does not carry one.
- A game's shift chart sometimes arrives late or not at all; until it does,
  the page shows the lines from the game before.

## Awards race

The **Awards** page (sixth page) shows who would win each of the league's
trophies if the season ended today (`pipeline/awards.py`).

- The **Art Ross** (most points), **Rocket Richard** (most goals),
  **Jennings** (goalies of the team allowing the fewest goals) and
  **Presidents' Trophy** (best record) are counts, shown as they stand.
- The others are voted on, so each list is the site's reading of the
  numbers, not a forecast of the vote. Every eligible regular is placed among
  the others on a few ingredients and the places are mixed into a score out
  of 100: **Hart** (70% Impact added, 30% his team's record), **Norris** (50%
  Impact, 30% points, 20% ice time, defensemen only), **Vezina** (50% goals
  saved above expected, 25% save percentage, 25% wins), **Calder** (60%
  Impact, 40% points, rookies only), **Selke** (30% plus-minus, 30% blocks
  and takeaways, 20% faceoffs won, 20% penalty-kill time, forwards only) and
  **Lady Byng** (60% points, 40% few penalty minutes). The weights are
  `RECIPES` at the top of `pipeline/awards.py`.
- The **Jack Adams** list ranks coaches by how far their team's share of the
  possible points is ahead of what its rating before the season pointed to.
- A rookie is as the league defines one: no earlier season of more than 25
  games, not two earlier seasons of 6 games or more, and under 26 on
  September 15.
- Each list shows the top five (ten on request). Once a week has passed, an
  arrow shows how far each name has moved in the last week.

## Team pages

Every team name on the site links to that team's page (`#/team/DAL`): its
record and places in the division, conference, league and GOAT ranking, the next five games and latest five
results, its team stats (each with its place among the 32), and its skaters
and goalies.

## Game pages and live box scores

Every game links to its own page (`#/game/<number>`). At the top is a **score
card**: the score, the goals period by period, each team's chance of winning
(before the game, for a finished one) and a side-by-side team comparison
(expected goals, shots, faceoffs, power play, hits, blocked shots, takeaways,
giveaways, penalty minutes). Below it are the goals in order with who assisted, the
three stars, and both teams' box scores: every skater's goals, assists,
plus-minus, shots, hits, blocks, penalty minutes, giveaways, takeaways,
faceoff percentage, shifts and ice time, and every goalie's shots, saves and
decision. Player names link to their cards.

- The score is read by the page itself from ESPN, every 15 seconds while a
  game is on.
- The NHL's own feed cannot be read by a web page directly, so the GitHub
  job fetches the box scores: on game days (September to June, about 11am to
  2am Central) it runs every 5 minutes, and when any game is under way it
  refreshes those games' box scores and the standings and rebuilds the site.
  When nothing is being played it stops within seconds. GitHub's scheduled
  runs are often a few minutes late.
- Games in progress show a red LIVE tag.

## Teams

The **Teams** page (`pipeline/teams.py`) shows each team's record and points,
goals for and against per game, shots for and against per game, expected
goals for and against per game and its share of them, shooting and save
percentage, power play and penalty kill, faceoffs won and penalty minutes
per game, where the site's rating places the team,
and strength of schedule (the average rating of its opponents, ranked among
the 32). Regular season only. A shootout win adds a goal to the final score
but is not counted as a goal scored.

## Players

The **Players** page ranks every regular against the rest, skaters together
and goalies on their own, and each name opens a card.

- **Impact per game** is the ranking number. Impact is a box-score rating in
  the style of hockey's "game score". Each thing a skater does is worth a set
  number of points: a goal 0.75, a first assist 0.70, a second assist 0.55, a
  shot on goal 0.075, a blocked shot 0.05, a takeaway 0.03 (a giveaway costs
  the same), a minor penalty drawn 0.15 (one taken costs the same), and each
  goal of plus-minus 0.15. His total is compared with what an average forward
  or defenseman would have piled up in the same ice time, so Impact is points
  added over an average player at his position. The reasoning is at the top
  of `pipeline/players.py`.
- **A goalie's Impact** is the goals he saved beyond what an average goalie
  would have on the same shots, counted separately at even strength, against
  the power play and shorthanded, at 0.75 a goal.
- **Percentiles** compare a player with regulars at his own position:
  forwards with forwards, defensemen with defensemen, goalies with goalies.
- **A regular** skater has played at least 40% of his team's games, a regular
  goalie 20%. Part-time players are listed (tick the box) but not ranked.
- A traded player is one player: his numbers from both teams are added up
  and he is listed with his new team.
- **Each card** also shows, from the play-by-play: a skater's shot attempts
  and expected goals per 60 minutes, his goals above expected (finishing) and
  his faceoff percentage; a goalie's goals saved above expected, which does
  account for where the shots came from. Season totals include power-play and
  shorthanded points, game-winning goals, shot attempts, expected goals and
  faceoffs. Below them is his **career**: every NHL regular season he has
  played, a career line and his career playoff totals, with where he was
  drafted; and then every game he has played this season, newest first.
- Earlier seasons come from the player's own page in the league's feed, read
  once and kept in `careers.json` (and read again every 30 days). This
  season's line is the site's own count from the box scores, so the career
  line is always up to date with the rest of the card.

What it cannot do: it sees only the box score, so it knows nothing about shot
quality, who else was on the ice, or how strong the opponent was. Early in
the season a game or two can move a player a long way. Regular season only.

## Player photos and details

Each player's full name, photo, height, weight, shooting hand, age and
birthplace come from his team's roster in the NHL's feed, read once a day. A
player who has played but is on no roster that day (sent to the minors, say)
is looked up on his own. The photos are not copied into this repository: the
site shows them from the NHL's site. To remove them all, set
`SHOW_PHOTOS = False` in `pipeline/config.py`.

## Team logos

Logos appear beside team names everywhere on the site. Each is shown in a white circle with a
ring (`.logo` in `site/styles.css`), straight from the NHL's site; they are
not stored in this repository. If a logo cannot be loaded, the team's short
code (DAL, COL) is shown in its place. To remove them, set `LOGO_URL = ""` in
`pipeline/config.py`.

## GOAT ranking

The Standings page's GOAT Ranking button shows the site's own ranking of the
32 teams (`pipeline/goat.py`), redone on every run. Five things decide it:

1. **Record:** the share of the possible points a team has won (weight 30%).
2. **Expected-goal share:** of the expected goals in its games, the share
   that were its own (30%). This says who has had the better chances,
   whatever the bounces.
3. **Goal share:** of the goals in its games, the share it scored (25%). A
   shootout win is not a goal.
4. **Strength of schedule:** the average rating of the teams it has played so
   far, each game counted once (15%). The ratings are the ones behind the odds.
5. **A hot streak:** a team that has won three or more in a row gets 0.02
   added for each win in the streak, up to 0.10.

For each of the first four a team gets its place among the 32, from 0 at the
bottom to 1 at the top, and those are combined with the weights above
(`GOAT_WEIGHTS` in `pipeline/config.py`; the streak settings are the
`GOAT_HOT_` lines beside it). The ranking is shown as a table like the
standings, with each team's place in the league, its strength of schedule,
its expected-goal and goal shares, and its streak in green when it is hot.

## Expected goals

The league's play-by-play gives every shot's place on the ice, its type and
what happened just before it. `pipeline/xg.py` turns that into each shot's
chance of going in: a shot from the slot might be worth 0.20 of a goal, one
from the blue line 0.02. Added up, they say what a team, a player or a goalie
"should" have scored or allowed on the chances there were.

- It counts unblocked shots (goals, saves and misses); blocked shots and
  shootouts are left out. A penalty shot is worth a flat 0.30, and a shot at
  an empty net has its own simple estimate from distance.
- The model is 150 small decision trees, fitted once on five seasons of shots
  (2021-22 to 2025-26) and kept in `model/xg.json`, so the job needs nothing
  installed to use it. Fitted on the first four of those seasons and tested
  on the fifth, it ranked a goal above a non-goal 76% of the time (77.5% with
  empty-net shots) and expected 8,941 goals where 8,572 were scored, 4% high.
- Because it runs a few percent high or low in any one season, the season's
  numbers are scaled so the league's expected goals equal the goals actually
  scored (`XG_STEADY_GOALS` in `pipeline/config.py` keeps the scale near 1
  early in the season).
- It sees where and how, not who: it does not know the shooter's skill, a
  screen in front, or whether the goalie was set.

Expected goals appear on the Teams page (for, against and share), in the GOAT
ranking, in each game's team comparison, and on player cards.

## Odds

Each game not yet played shows both teams' chance of winning, the favorite
in bold. These are the site's own estimate, not a sportsbook's line.

- Every team has a rating, built from goals for and against and who they
  were against. It moves after each game, quickly early in the season and
  slowly later, and a team starts each season on 80% of where it finished
  the last one. Home ice is worth a little; at neutral sites it is left out.
  A win by more than four goals counts as four.
- Tested on 5,592 games from 2022-23 to 2025-26, always predicting from what
  was known beforehand, the favorite won 58.0% of the time (the home team
  wins 53.5%), and the percentages were honest: teams given 60 to 70% won
  65%. Hockey is close: few games are ever more lopsided than 70-30.
- It knows results, not rosters: an injury or a trade only shows once the
  scores change, and it does not know who is starting in goal.
- Ratings are kept in `ratings.json` on the `state` branch, so next season
  starts from this one by itself. `ratings/seed.json` holds where teams
  finished 2025-26, for this first season. The settings are in
  `pipeline/config.py` and the method at the top of `pipeline/odds.py`.

## Where to watch

Each game still to come shows the channels and streaming services the league
lists for it: national ones first (ESPN, TNT, ESPN+ and so on), then the two
teams' own channels, American before Canadian, four at most. "No broadcast
listed" means the league names none yet for a game in the next two weeks.
Channels are refreshed on every run and can change late; the footer says so.

## Live scores

While a game is being played, the page itself re-reads ESPN's public
scoreboard every 15 seconds and updates that game's row: the score, the
period and the time left, and "Final" when it ends. This happens in the
reader's browser, so it needs no extra runs on GitHub. It starts 15 minutes
before a game's listed start time and pauses while the tab is in the
background. If ESPN cannot be reached, the row simply stays as it was (the
job's own five-minute refresh still moves it along).

## When it updates

The file `.github/workflows/update.yml` tells GitHub when to run:

| When | What it does |
| --- | --- |
| Every morning about 5:47am Central, and again about 11:47am | Schedule, scores, channels, standings, box scores, play-by-play, rosters, ratings and the GOAT ranking |
| Every night about 3:17am Central | A third full refresh, once the late games on the west coast are over |
| Every 5 minutes, 11am to 2am Central, September to June | Scores, box scores and standings while a game is under way |
| Whenever the code changes, or you press **Run workflow** on the **Actions** tab | Everything, straight away (after running the tests) |

## A new season, trades and new teams

Nothing needs doing. On September 1 the job starts looking for the new
season's schedule, and the ratings carry over. Players, teams and their
names all come from the league's feed, so a trade, a call-up, a renamed or a
new team shows up on the next run. The playoffs are listed on the Games page
with their round; standings, team stats and player ratings stay regular
season only.

If the league's feed cannot be read, the site keeps what it had, the run is
marked failed, it shows red on the Actions tab and GitHub emails you. It
tries again on the next run by itself.

## Changing the wording

All the site's headings, intro lines, notes, button labels and the footer are
in one file, `site/words.txt`, one `name = words` line each. Change the words
after the `=` on GitHub (open the file, click the pencil, then Commit changes)
and the site updates in about two minutes. A broken line stops the update and
leaves the old site up; GitHub emails you, and the run log names the line.

## Where things are

| Path | What it is |
| --- | --- |
| `pipeline/config.py` | Every setting: season dates, odds settings, GOAT weights, what to show |
| `pipeline/nhl.py` | Reads the league's feed: schedule, standings, box scores, rosters |
| `pipeline/players.py` | Rates the players against each other and works out percentiles |
| `pipeline/awards.py` | The awards races: counts for four trophies, a score for the voted ones |
| `pipeline/lines.py` | Line combinations: who was on the ice together, from the shift charts |
| `pipeline/careers.py` | Each player's earlier seasons, joined to this one for his career table |
| `pipeline/teams.py` | Adds up each team's stats from the box scores |
| `pipeline/goat.py` | The GOAT ranking: record, schedule, expected-goal share, goal share and a hot-streak boost |
| `pipeline/xg.py` | Expected goals: reads the play-by-play and gives each shot its chance of scoring |
| `model/xg.json` | The expected-goals model itself |
| `pipeline/odds.py` | Rates every team from results and turns two ratings into a chance of winning |
| `pipeline/web.py` | Downloading, with retries |
| `pipeline/run.py` | The job: update everything stored, then build the page |
| `ratings/seed.json` | Where each team's rating finished 2025-26 |
| `site/` | The page itself (plain HTML, CSS and JavaScript, no build step) |
| `tests/` | Checks that the feed's documents are read correctly and the site builds |

Run the tests with `python tests/run_local.py`.

Two side branches of this repository hold what the job produces:

- `state`: the season's games (`schedule.json`), the standings
  (`standings.json`), the box scores with what was taken from each game's
  play-by-play (`box.json`), players' earlier seasons (`careers.json`), who was on the ice together in each game (`lines.json`), players' details
  (`people.json`), the ratings (`ratings.json`), and what happened on the
  last run (`status.json`, `logs/last_run.log`).
- `gh-pages`: the finished page.

## Turning the website on

It is already on. If it ever needs doing again, in the repository's
**Settings → Pages → Build and deployment → Source: "Deploy from a branch"**,
choose branch `gh-pages` and folder `/ (root)`, and save.

The page is at `https://dougmullendore.github.io/Hockey/`.

## Good to know

- The numbers beside teams are today's places in the standings, including on
  earlier weeks' games.
- A game's date is the league's own date for it (the date where it is
  played), while its time is shown in the reader's time zone, so a late game
  on the west coast can show a time after midnight.
- The earlier, larger version of this site (expected goals, WAR, player
  cards, contracts, playoff odds) is in this repository's history, last at
  commit `e01f7ce`. The games it stored are still on the `data` branch, which
  the new site does not use.
- GitHub switches off scheduled jobs in a repository with no activity for 60
  days. Each run switches the job back on, so the updates keep going through
  the summer without anyone committing.

Not affiliated with or endorsed by the NHL or any team.
