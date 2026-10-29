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

Each game's props are pulled **once, on the morning of game day**: 5 prop types
cost 5 credits per game, or about 75 a week. Spreads and totals for the whole slate cost
2 credits per daily run. That comes to about 385 of the 500 monthly credits. The code refuses to make
an odds call if fewer than 25 credits remain.

## Checking the setup

Go to **Actions**, click **Setup check**, then **Run workflow**. All four lines in the
run summary should show ✅.

_Bet responsibly. If gambling stops being fun, call 1-800-GAMBLER._
