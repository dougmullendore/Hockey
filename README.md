# GOAT Hockey

An advanced NHL stats website. Every night it downloads the league's public
play-by-play data, rates every shot with an expected-goals model, and rebuilds
the site.

You do not need to run anything. GitHub does it all on a schedule.

## What is on the site

| Page | What it shows |
| --- | --- |
| Home | A shot map for each recent game, plus season leaders |
| Games | Every game: the score next to the expected goals; plus win probabilities for the next week |
| Standings | Projected points, playoff odds and Stanley Cup odds from simulating the rest of the season |
| WAR | Wins above replacement for every skater and goalie, split into its parts |
| Cards | One card per player: where he ranks at his position in each part of his game |
| Contracts | Cap hit next to what each player's play is worth: who is a bargain and who is not |
| Goalies | Goals saved above expected, overall and on high-danger shots |
| Skaters | Goals, assists, individual expected goals, finishing; plus on-ice results at five-on-five |
| Lines | Forward lines, defense pairs, and how any two teammates do with and without each other |
| Teams | Expected goals share, Corsi, PDO, finishing and goaltending |
| About | How the model works and how well it tested |

Seasons covered: 2021-22 to today. A new season is added automatically each
September.

## How it runs

The file `.github/workflows/update.yml` tells GitHub to run the pipeline:

- every night at about 5:20am Central
- whenever the code changes
- whenever you press **Run workflow** on the repository's **Actions** tab

Each run does these things, in order:

1. **Fetch**: download any finished games not stored yet (play-by-play and
   shift charts), and re-check the last three days for the league's stat
   corrections.
2. **Model**: train the expected-goals model if there isn't one, or if a
   season has just finished. Otherwise skip.
3. **Stats**: score every shot and build the goalie, skater, team and game
   tables.
4. **Odds**: rate every team, predict the coming week's games, and simulate
   the rest of the season for playoff and Stanley Cup odds.
5. **Site**: put the pages and tables together.

Results are stored on two side branches of this repository:

- `data`: the downloaded games, the model, and `status.json` (what happened
  on the last run). `logs/last_run.log` has the full log.
- `gh-pages`: the finished website.

## Turning the website on

One-time setup in the repository's **Settings**:

1. **Settings → General → Danger Zone → Change visibility → Public.**
   GitHub's free plan only hosts websites from public repositories. (Skip
   this if you pay for GitHub Pro.)
2. **Settings → Pages → Build and deployment → Source: Deploy from a branch**,
   then choose branch **gh-pages** and folder **/ (root)**, and save.

A minute later the site is live at
`https://<your-username>.github.io/Hockey/`.

## Where things are

| Folder | What it is |
| --- | --- |
| `pipeline/config.py` | Settings: site name, first season, model options |
| `pipeline/fetch.py`, `parse.py` | Downloading games and tidying them |
| `pipeline/features.py`, `xg.py` | The expected-goals model |
| `pipeline/onice.py` | Who was on the ice for every shot (from shift charts) |
| `pipeline/rapm.py`, `war.py` | Isolating each player's impact, and wins above replacement |
| `pipeline/cards.py` | Player card percentiles |
| `pipeline/contracts.py` | Cap hits set against dollar values (optional) |
| `pipeline/predict.py` | Game win probabilities and the season simulation |
| `pipeline/aggregate.py` | The tables shown on the site |
| `site/` | The web pages (HTML, CSS, JavaScript) |
| `tests/` | Checks run against four real games |

To rename the site, change `SITE_NAME` in `pipeline/config.py`.

**Once a year:** when the league announces the next season's salary cap, add
that season's cap and minimum salary to `SALARY_CAP` in `pipeline/config.py`.
Dollar values use the newest line until then.

## Contract figures

The NHL's feeds do not include salaries, so the Contracts page reads cap hits
from `contracts/cap_hits.csv`: one line per contract, with the columns
`team,last,first,pos,cap_hit,expiry_status,section,checked`.
`contracts/info.json` holds the date the figures were looked up, which the
page shows.

This file does **not** update itself. It is a snapshot from one day, and goes
out of date with every signing and trade. Ask for a refresh a few times a
season (after the July signing period, at the start of the season, and after
the trade deadline). If the file is deleted, the Contracts page and its menu
link are simply left out.

## Not affiliated with the NHL

Data comes from the NHL's public game feeds. This project is not affiliated
with or endorsed by the NHL or any team.
