"""Phase 1 setup check.

Confirms every free data source answers and the Odds API key works.
Uses at most 1 Odds API credit (one prop market for one game).
Results are printed and written to the GitHub Actions run summary.
"""

import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from propex import config  # noqa: E402

results = []  # (name, ok, detail)


def check(name):
    def wrap(fn):
        try:
            detail = fn()
            results.append((name, True, detail))
        except Exception as exc:  # report every failure, keep going
            results.append((name, False, f"{type(exc).__name__}: {exc}"))
        return fn
    return wrap


@check("nflverse stats (nflreadpy)")
def _nflverse():
    import nflreadpy as nfl
    sched = nfl.load_schedules(config.SEASON)
    return f"{sched.height} games on the {config.SEASON} schedule"


@check("Open-Meteo weather")
def _weather():
    # Gillette Stadium, Foxborough MA
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={"latitude": 42.0909, "longitude": -71.2643,
                "hourly": "wind_speed_10m", "wind_speed_unit": "mph",
                "forecast_days": 1},
        timeout=30,
    )
    r.raise_for_status()
    wind = r.json()["hourly"]["wind_speed_10m"][12]
    return f"forecast received (Foxborough wind at noon: {wind} mph)"


@check("ESPN injury reports")
def _espn():
    r = requests.get(
        "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/teams/17/injuries",
        params={"limit": 100}, timeout=30,
    )
    r.raise_for_status()
    return f"{r.json().get('count', 0)} injury entries for New England"


@check("The Odds API key + player props")
def _odds():
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        raise RuntimeError("ODDS_API_KEY secret is missing")
    # Listing events is free (costs 0 credits).
    r = requests.get(f"{config.ODDS_API_BASE}/sports/{config.ODDS_SPORT}/events",
                     params={"apiKey": key}, timeout=30)
    r.raise_for_status()
    events = r.json()
    left = int(r.headers.get("x-requests-remaining", 0))
    if not events:
        return f"key works, no upcoming games listed, {left} credits left"
    if left < config.MIN_CREDITS_LEFT:
        return f"key works, skipped props test to save credits ({left} left)"
    # One prop market for one game = 1 credit.
    ev = events[0]
    r = requests.get(
        f"{config.ODDS_API_BASE}/sports/{config.ODDS_SPORT}/events/{ev['id']}/odds",
        params={"apiKey": key, "regions": config.ODDS_REGION,
                "markets": "player_reception_yds", "oddsFormat": "american"},
        timeout=30,
    )
    r.raise_for_status()
    books = r.json().get("bookmakers", [])
    lines = sum(len(m["outcomes"]) for b in books for m in b["markets"])
    left = r.headers.get("x-requests-remaining", "?")
    if not lines:
        return (f"key works, but no receiving-yard props posted yet for "
                f"{ev['away_team']} @ {ev['home_team']} ({left} credits left)")
    return (f"props available on free plan: {lines} receiving-yard lines for "
            f"{ev['away_team']} @ {ev['home_team']} ({left} credits left)")


def main():
    lines = ["## The Prop Exchange: setup check", ""]
    for name, ok, detail in results:
        lines.append(f"- {'✅' if ok else '❌'} **{name}**: {detail}")
    text = "\n".join(lines)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        Path(summary).write_text(text + "\n")
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)


if __name__ == "__main__":
    main()
