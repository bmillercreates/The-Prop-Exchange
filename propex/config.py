"""Settings shared by every part of The Prop Exchange."""

SEASON = 2026

# The Odds API (free Starter plan = 500 credits per month).
# Cost of one call = (number of markets that come back) x (number of regions).
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_SPORT = "americanfootball_nfl"
# Up to 10 bookmakers count as one "region", so asking for two costs nothing extra.
ODDS_BOOKMAKERS = "draftkings,fanduel"

# Prop types we track. Each one costs 1 credit per game when pulled.
PROP_MARKETS = [
    "player_pass_yds",
    "player_rush_yds",
    "player_reception_yds",
    "player_receptions",
    "player_anytime_td",
]

# Game lines (spread + total) for the whole slate in one call = 2 credits.
GAME_LINE_MARKETS = ["spreads", "totals"]

# Safety guard: never make an odds call if fewer credits than this remain.
MIN_CREDITS_LEFT = 25
