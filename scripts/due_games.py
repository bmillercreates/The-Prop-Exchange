"""Which games need their FINAL pre-kickoff run right now?

A game is due when it kicks off within the next 80 minutes and its picks
aren't FINAL yet. Inactives come out 90 minutes before kickoff, and this
check runs every 15 minutes, so each game is caught 65-80 minutes out.
GitHub sometimes starts scheduled runs late. Any game that's still not FINAL
is picked up by the next run, all the way up to kickoff.

Uses only the Python standard library, so the workflow can check this in a
few seconds and skip the rest when nothing is due.
Prints the due game ids, space separated (empty when none are due).
"""

import csv
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
WINDOW = timedelta(minutes=80)


def main():
    now = datetime.now(ET)
    due = []
    with open(ROOT / "data" / "stats" / "games.csv") as f:
        for g in csv.DictReader(f):
            kickoff = datetime.fromisoformat(f"{g['gameday']}T{g['gametime']}").replace(tzinfo=ET)
            if not (now < kickoff <= now + WINDOW):
                continue
            card = ROOT / "data" / "picks" / f"{g['game_id']}.json"
            if card.exists() and json.loads(card.read_text()).get("status") == "FINAL":
                continue
            due.append(g["game_id"])
    ids = " ".join(due)
    print(ids or "No games due.")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as out:
            out.write(f"games={ids}\n")


if __name__ == "__main__":
    main()
