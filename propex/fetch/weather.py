"""Kickoff weather for upcoming outdoor games, from Open-Meteo (free, no key).

Output: data/weather.json, keyed by game_id.
Domes and closed retractable roofs are marked "covered" and not looked up.
"""

from datetime import datetime, timedelta

import requests

from propex import stadiums
from propex.paths import DATA, ET, save_json

URL = "https://api.open-meteo.com/v1/forecast"
FORECAST_DAYS = 14  # Open-Meteo forecasts up to 16 days ahead


def _kickoff(game):
    return datetime.fromisoformat(f"{game['gameday']}T{game['gametime']}").replace(tzinfo=ET)


def _forecast(lat, lon, kickoff):
    r = requests.get(URL, params={
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,wind_speed_10m,wind_gusts_10m,precipitation,"
                  "precipitation_probability",
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
        "precipitation_unit": "inch", "timezone": "America/New_York",
        "start_date": kickoff.date().isoformat(),
        "end_date": (kickoff + timedelta(hours=4)).date().isoformat(),
    }, timeout=30)
    r.raise_for_status()
    h = r.json()["hourly"]
    # The 3 game hours starting at kickoff (times come back in Eastern time)
    start = kickoff.replace(minute=0).strftime("%Y-%m-%dT%H:%M")
    i = h["time"].index(start)
    window = slice(i, i + 3)
    return {
        "temp_f": round(sum(h["temperature_2m"][window]) / 3),
        "wind_mph": round(max(h["wind_speed_10m"][window])),
        "gust_mph": round(max(h["wind_gusts_10m"][window])),
        "precip_in": round(sum(h["precipitation"][window]), 2),
        "precip_chance": max(h["precipitation_probability"][window]),
    }


def run(upcoming_games):
    """upcoming_games: list of dicts (rows of games.csv) not yet played."""
    out = {}
    now = datetime.now(ET)
    for g in upcoming_games:
        kickoff = _kickoff(g)
        if kickoff - now > timedelta(days=FORECAST_DAYS):
            continue
        entry = {"game_id": g["game_id"], "stadium": g["stadium"],
                 "kickoff_et": kickoff.isoformat()}
        info = stadiums.lookup(g["stadium_id"], g["stadium"])
        if stadiums.is_covered(g["stadium_id"], g["stadium"], g["roof"]):
            entry["covered"] = True
        elif info is None:
            entry["error"] = f"unknown stadium {g['stadium_id']}"
        else:
            entry["covered"] = False
            try:
                entry.update(_forecast(info[0], info[1], kickoff))
            except Exception as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
        out[g["game_id"]] = entry
    save_json(DATA / "weather.json", out)
    looked_up = sum(1 for e in out.values() if "wind_mph" in e)
    print(f"weather: {looked_up} outdoor forecasts, "
          f"{sum(1 for e in out.values() if e.get('covered'))} covered stadiums skipped")
    return out
