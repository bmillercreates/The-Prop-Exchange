"""Injury report designations (Out / Doubtful / Questionable).

Main source: ESPN's free public injuries feed (updates through the week).
Backup: nflverse's copy of the official NFL injury report.
Official game-day inactives are not in either feed, so the model treats
"Out" and "Doubtful" as not playing and "Questionable" as a risk flag.

Output: data/injuries.csv
"""

import nflreadpy as nfl
import polars as pl
import requests

from propex import config
from propex.paths import DATA, save_csv

ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"

# ESPN team names -> nflverse abbreviations are matched through load_teams()
COLUMNS = ["team", "player", "position", "status", "detail", "source"]


def _espn(team_lookup):
    r = requests.get(ESPN_URL, timeout=30)
    r.raise_for_status()
    rows = []
    for team in r.json().get("injuries", []):
        abbr = team_lookup.get(team.get("displayName", ""))
        for inj in team.get("injuries", []):
            ath = inj.get("athlete", {})
            details = inj.get("details", {})
            rows.append({
                "team": abbr,
                "player": ath.get("displayName"),
                "position": (ath.get("position") or {}).get("abbreviation"),
                "status": inj.get("status"),
                "detail": details.get("type") or inj.get("shortComment", "")[:80],
                "source": "espn",
            })
    return pl.DataFrame(rows, schema=dict.fromkeys(COLUMNS, pl.Utf8))


def _nflverse():
    inj = nfl.load_injuries(config.SEASON)
    latest = inj.filter(pl.col("week") == inj["week"].max())
    return latest.select(
        "team", pl.col("full_name").alias("player"), "position",
        pl.col("report_status").alias("status"),
        pl.col("report_primary_injury").alias("detail"),
        pl.lit("nflverse").alias("source"),
    ).filter(pl.col("status").is_not_null())


def run():
    teams = nfl.load_teams()
    team_lookup = dict(zip(teams["team_name"], teams["team_abbr"]))
    try:
        df = _espn(team_lookup)
        if df.height == 0:
            raise ValueError("ESPN returned no injuries")
    except Exception as exc:
        print(f"injuries: ESPN failed ({exc}), using nflverse backup")
        df = _nflverse()
    save_csv(DATA / "injuries.csv", df)
    counts = df.group_by("status").len().sort("len", descending=True)
    summary = ", ".join(f"{s}: {n}" for s, n in counts.iter_rows())
    print(f"injuries ({df['source'][0] if df.height else 'none'}): {summary}")
    return df
