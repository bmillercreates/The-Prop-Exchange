"""Run the model and save picks for upcoming games.

Usage:
  python scripts/run_model.py                 every upcoming game (PRELIMINARY)
  python scripts/run_model.py --final ID ...  only these games, marked FINAL

Games without prop lines yet still get projections, just no picks.
Output: data/picks/<game_id>.json
"""

import argparse
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from propex.model import picks as picker  # noqa: E402
from propex.model.project import load_inputs, project_game  # noqa: E402
from propex.paths import DATA, ODDS, PROPS, STATS, load_json, now_et, save_json  # noqa: E402

PICKS = DATA / "picks"


def run_game(game, data, status):
    projections = project_game(game, data)
    props = load_json(PROPS / f"{game['game_id']}.json")
    result = {"blue_chips": [], "penny_stocks": [], "etfs": []}
    if props:
        result = picker.select(picker.build_candidates(projections, props["props"]))
    weather = data["weather"].get(game["game_id"], {})
    ctx = {p["team"]: p["ctx"] for p in projections}
    out = {
        "game_id": game["game_id"], "status": status,
        "updated_at": now_et().isoformat(timespec="minutes"),
        "kickoff": f"{game['gameday']}T{game['gametime']}", "weekday": game["weekday"],
        "away": game["away_team"], "home": game["home_team"], "stadium": game["stadium"],
        "has_props": bool(props),
        "props_pulled_at": props["pulled_at"] if props else None,
        "weather": weather,
        "teams": {t: {"implied_pts": round(c["implied_pts"], 1), "margin": c["margin"],
                      "plays": round(c["plays"], 1), "pass_att": round(c["pass_att"], 1),
                      "notes": c["notes"]} for t, c in ctx.items()},
        **result,
        "projections": [{
            "player": p["player"], "team": p["team"], "position": p["position"],
            **{k: round(v, 1) for k, v in p["proj"].items()},
        } for p in projections if max(p["proj"].get("rec_yds", 0), p["proj"].get("rush_yds", 0),
                                      p["proj"].get("pass_yds", 0)) >= 10],
    }
    save_json(PICKS / f"{game['game_id']}.json", out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", nargs="*", help="game ids to mark FINAL")
    args = ap.parse_args()

    data = load_inputs(STATS, DATA, ODDS)
    import nflreadpy as nfl
    teams = nfl.load_teams()
    picker.TEAM_NICK.update(dict(zip(teams["team_abbr"], teams["team_nick"])))

    now = now_et().strftime("%Y-%m-%d %H:%M")
    games = data["games"].filter((pl.col("gameday") + " " + pl.col("gametime")) > now)
    if args.final:
        games = games.filter(pl.col("game_id").is_in(args.final))
    # Only the current week: games in the next 7 days
    week = games.sort("gameday")["week"].head(1).to_list()
    games = games.filter(pl.col("week").is_in(week))
    for g in games.iter_rows(named=True):
        status = "FINAL" if args.final else "PRELIMINARY"
        # never downgrade a FINAL card back to preliminary
        existing = load_json(PICKS / f"{g['game_id']}.json")
        if existing and existing.get("status") == "FINAL" and not args.final:
            continue
        out = run_game(g, data, status)
        n = len(out["blue_chips"]) + len(out["penny_stocks"]) + len(out["etfs"])
        print(f"model: {g['game_id']} {status}: {n} picks"
              + ("" if out["has_props"] else " (no prop lines yet)"))


if __name__ == "__main__":
    main()
