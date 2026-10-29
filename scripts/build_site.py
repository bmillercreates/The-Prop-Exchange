"""Bundle this week's picks into site/data.json for the website.

The website itself (site/index.html) is static: it just reads data.json.
"""

import sys
from pathlib import Path

import nflreadpy as nfl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from propex.paths import DATA, ROOT, load_json, now_et, save_json  # noqa: E402

TOP_PROJECTIONS = 4  # per team, for games whose prop lines aren't out yet


def main():
    cards = [load_json(f) for f in sorted((DATA / "picks").glob("*.json"))]
    if cards:
        week = max(int(c["game_id"].split("_")[1]) for c in cards)
        cards = [c for c in cards if int(c["game_id"].split("_")[1]) == week]
    else:
        week = None
    cards.sort(key=lambda c: c["kickoff"])
    for c in cards:
        keep = []
        for team in (c["away"], c["home"]):
            rows = [p for p in c["projections"] if p["team"] == team]
            rows.sort(key=lambda p: max(p.get("pass_yds", 0) / 3, p.get("rush_yds", 0),
                                        p.get("rec_yds", 0)), reverse=True)
            keep += rows[:TOP_PROJECTIONS]
        c["projections"] = keep

    teams = nfl.load_teams()
    team_info = {r["team_abbr"]: {"name": r["team_name"], "nick": r["team_nick"],
                                  "color": r["team_color"], "color2": r["team_color2"]}
                 for r in teams.iter_rows(named=True)}
    credits = load_json(DATA / "odds" / "credits.json", {}).get("remaining")
    save_json(ROOT / "site" / "data.json", {
        "generated_at": now_et().isoformat(timespec="minutes"),
        "season": 2026, "week": week, "credits_left": credits,
        "teams": team_info, "games": cards,
    })
    print(f"site: week {week}, {len(cards)} games")


if __name__ == "__main__":
    main()
