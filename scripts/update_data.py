"""Refresh every data source and save the results in data/.

  python scripts/update_data.py                 daily refresh of everything
  python scripts/update_data.py --games ID ...  pre-kickoff refresh for those games:
                                                injuries and weather, plus props only
                                                if they weren't pulled yet (no stats
                                                download, no spread/total pull)

Each source is independent: if one fails, the others still update and the
run reports the failure.
"""

import argparse
import sys
import traceback
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from propex.fetch import injuries, nflverse_data, odds, weather  # noqa: E402
from propex.paths import STATS, now_et  # noqa: E402


def main():
    failures = []

    def step(name, fn, *args):
        try:
            return fn(*args)
        except Exception:
            failures.append(name)
            print(f"{name}: FAILED")
            traceback.print_exc()

    ap = argparse.ArgumentParser()
    ap.add_argument("--games", nargs="*", help="pre-kickoff mode: only these game ids")
    args = ap.parse_args()

    if args.games:
        games = pl.read_csv(STATS / "games.csv", infer_schema_length=0)
        due = games.filter(pl.col("game_id").is_in(args.games)).to_dicts()
        step("weather", weather.run, due)
        step("injuries", injuries.run)
        step("odds", odds.run, due, False, set(args.games))
    else:
        games = step("nflverse", nflverse_data.run)
        if games is None:
            sys.exit(1)  # everything else depends on the schedule
        today = now_et().date().isoformat()
        upcoming = games.filter(pl.col("gameday") >= today).to_dicts()
        step("weather", weather.run, upcoming)
        step("injuries", injuries.run)
        step("odds", odds.run, upcoming)

    if failures:
        print(f"Finished with problems in: {', '.join(failures)}")
        sys.exit(1)
    print("All data updated.")


if __name__ == "__main__":
    main()
