"""Storylines: fun facts for each game. Shown on the site, never used by the model.

  Birthday   a player whose birthday falls on game day
  Revenge    a player facing a team he used to play for
  Milestone  a player who could reach a season milestone in this game

Output: data/storylines.json, keyed by game_id.
"""

from datetime import date

import nflreadpy as nfl
import polars as pl

from propex import config
from propex.paths import DATA, STATS, load_json, save_json

FIRST_HISTORY_SEASON = 2016
OLD_ABBR = {"OAK": "LV", "SD": "LAC", "STL": "LA"}
MILESTONES = {
    "receiving_yards": ("receiving yards", "rec_yds", [500, 1000, 1500]),
    "rushing_yards": ("rushing yards", "rush_yds", [500, 1000, 1500]),
    "passing_yards": ("passing yards", "pass_yds", [2000, 3000, 4000, 5000]),
    "receptions": ("catches", "receptions", [50, 75, 100]),
    "passing_tds": ("passing TDs", None, [20, 30, 40]),
    "scrimmage_tds": ("total TDs", "tds", [5, 10, 15]),  # rushing + receiving
}
MAX_PER_TYPE = 3


def _relevant_players(pg):
    """Skill players with a real role this season, keyed by player id."""
    agg = pg.group_by("player_id").agg(
        pl.col("player").last(), pl.col("position").last(), pl.col("team").last(),
        pl.len().alias("games"), pl.col("snap_share").mean().alias("snap"),
        pl.col("targets").sum(), pl.col("carries").sum(), pl.col("attempts").sum(),
        pl.col("receiving_yards").sum(), pl.col("rushing_yards").sum(),
        pl.col("passing_yards").sum(), pl.col("receptions").sum(), pl.col("passing_tds").sum(),
        (pl.col("receiving_tds") + pl.col("rushing_tds")).sum().alias("scrimmage_tds"))
    return agg.filter((pl.col("snap") >= 0.3) | (pl.col("targets") + pl.col("carries") >= 20)
                      | (pl.col("attempts") >= 50))


def _birthdays(game, players, relevant):
    gameday = date.fromisoformat(game["gameday"])
    out = []
    ids = set(relevant["player_id"])
    rows = players.filter(pl.col("team").is_in([game["away_team"], game["home_team"]])
                          & pl.col("player_id").is_in(ids) & pl.col("birth_date").is_not_null())
    for r in rows.iter_rows(named=True):
        born = date.fromisoformat(r["birth_date"][:10])
        if (born.month, born.day) == (gameday.month, gameday.day):
            age = gameday.year - born.year
            out.append({"type": "Birthday", "player": r["full_name"], "team": r["team"],
                        "text": f"{r['full_name']} ({r['team']} {r['position']}) turns {age} on game day."})
    return out[:MAX_PER_TYPE]


def _revenge(game, history, relevant, nick):
    out = []
    for team, opp in ((game["away_team"], game["home_team"]), (game["home_team"], game["away_team"])):
        on_team = relevant.filter(pl.col("team") == team)
        for r in on_team.iter_rows(named=True):
            past = history.filter((pl.col("gsis_id") == r["player_id"]) & (pl.col("team") == opp))
            if past.height == 0:
                continue
            seasons = sorted(set(past["season"]))
            span = (f"in {seasons[0]}" if len(seasons) == 1
                    else f"from {seasons[0]} to {seasons[-1]}")
            out.append({"type": "Revenge", "player": r["player"], "team": team,
                        "weight": r["targets"] + r["carries"] + r["attempts"],
                        "text": f"{r['player']} ({team} {r['position']}) faces the {nick.get(opp, opp)}, "
                                f"the team he played for {span}."})
    out.sort(key=lambda x: -x.pop("weight"))
    return out[:MAX_PER_TYPE]


def _amount(need, label):
    if need == 1:
        return "1 more " + label.replace("TDs", "TD").replace("catches", "catch").replace("yards", "yard")
    return f"{need:g} more {label.split(' (')[0]}"


def _milestones(game, relevant, card):
    proj = {p["player"]: p for p in (card or {}).get("projections", [])}
    out = []
    for r in relevant.filter(pl.col("team").is_in([game["away_team"], game["home_team"]])).iter_rows(named=True):
        p = proj.get(r["player"], {})
        for col, (label, proj_key, marks) in MILESTONES.items():
            have = r[col] or 0
            target = next((m for m in marks if m > have), None)
            if target is None:
                continue
            need = target - have
            if col.endswith("tds"):
                chance = 1 - 2.718281828 ** -p.get("tds", 0) if proj_key else 0
                close = need == 1 and (chance >= 0.3 or col == "passing_tds")
            else:
                expected = p.get(proj_key, 0) if proj_key else 0
                close = expected > 0 and need <= expected * 1.3
            if close:
                out.append({"type": "Milestone", "player": r["player"], "team": r["team"],
                            "need": need / target,
                            "text": f"{r['player']} needs {_amount(need, label)} to reach "
                                    f"{target:,} for the season (has {have:,.0f})."})
    out.sort(key=lambda x: x.pop("need"))
    return out[:MAX_PER_TYPE]


def run(upcoming_games):
    pg = pl.read_csv(STATS / "player_games.csv", infer_schema_length=10000)
    players = pl.read_csv(STATS / "players.csv", infer_schema_length=0)
    relevant = _relevant_players(pg)
    history = nfl.load_rosters(list(range(FIRST_HISTORY_SEASON, config.SEASON))).select(
        "season", "gsis_id", pl.col("team").replace(OLD_ABBR))
    # earlier this season counts too (players traded or cut mid-year)
    this_year = nfl.load_rosters_weekly(config.SEASON).select(
        "season", "gsis_id", "team")
    history = pl.concat([history, this_year]).unique()

    teams = nfl.load_teams()
    nick = dict(zip(teams["team_abbr"], teams["team_nick"]))
    out = {}
    for g in upcoming_games:
        card = load_json(DATA / "picks" / f"{g['game_id']}.json")
        items = _birthdays(g, players, relevant) + _revenge(g, history, relevant, nick) + _milestones(g, relevant, card)
        out[g["game_id"]] = items
    save_json(DATA / "storylines.json", out)
    print(f"storylines: {sum(len(v) for v in out.values())} across {len(out)} games")
    return out
