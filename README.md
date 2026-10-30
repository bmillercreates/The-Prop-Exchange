# The Prop Exchange

NFL player prop picks with a stock-market look. Built for personal use with friends.

- **Blue Chips**: the strongest picks
- **Penny Stocks**: plus-money longshots
- **ETFs**: parlays made from picks that tend to hit together
- **Portfolio Performance**: how every pick has done

## How it works

- `propex/`: the Python code that pulls data and runs the model
- `scripts/`: small programs the scheduled jobs run
- `data/`: saved data and picks
- `site/`: the website, published free on GitHub Pages
- `.github/workflows/`: the schedules that run everything automatically

## Free data sources

| Source | Used for | Cost |
| --- | --- | --- |
| nflverse (nflreadpy) | stats, snaps, rosters, birthdates | free |
| Open-Meteo | stadium weather | free (non-commercial) |
| ESPN public feeds | injury reports | free |
| The Odds API | sportsbook lines | free plan, 500 credits a month |

### Odds API budget

- Listing games: free.
- Spreads and totals for the whole slate: 2 credits, once a day (about 52 a month).
- Player props: 5 prop types = 5 credits per game, pulled **once** per game. The
  daily run pulls Thursday/Sunday games that morning; Monday (and London) games
  are pulled by the pre-kickoff run. Total is about 350 a month.

That's about 400 of the 500 monthly credits. The code refuses to make a paid
call if fewer than 25 credits remain.

## Schedule (all automatic)

| Workflow | When | What it does |
| --- | --- | --- |
| Update data | 10 AM ET (11 AM during daylight time), Tue–Sun | stats, injuries, weather, lines, then PRELIMINARY picks, Storylines and a site rebuild; then starts the game-day runner |
| Game-day runner | runs continuously around game days | waits on its own until 80 min before each kickoff (fresh injuries and weather, then FINAL picks), and grades each game about 3h20m after kickoff |
| Game-day runner backup check | whenever GitHub runs it (scheduled twice an hour) | restarts the runner if it isn't running |
| Publish website | after any of the above | rebuilds the GitHub Pages site |
| Grade picks | manual only | regrade, or print one game's box score |

GitHub often skips or delays frequent scheduled runs, so the timed work isn't
left to the scheduler: the runner sleeps until each job is due, and before
GitHub's 6-hour job limit it starts a fresh copy of itself.

## Checking the setup

Go to **Actions**, click **Setup check**, then **Run workflow**. All four lines in the
run summary should show ✅.

_Bet responsibly. If gambling stops being fun, call 1-800-GAMBLER._
