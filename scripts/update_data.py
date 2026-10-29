"""Refresh every data source and save the results in data/.

Run by the "Update data" GitHub workflow. Each source is independent:
if one fails, the others still update and the run reports the failure.
"""

import sys
import traceback
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from propex.fetch import injuries, nflverse_data, odds, weather  # noqa: E402
from propex.paths import now_et  # noqa: E402


def main():
    failures = []

    def step(name, fn, *args):
        try:
            return fn(*args)
        except Exception:
            failures.append(name)
            print(f"{name}: FAILED")
            traceback.print_exc()

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
