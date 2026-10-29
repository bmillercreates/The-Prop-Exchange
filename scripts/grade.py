"""Grade finished games and update Portfolio Performance.

Usage:
  python scripts/grade.py              grade every finished game not yet graded
  python scripts/grade.py --check ID   just print the box score we'd grade ID with
"""

import argparse
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from propex import grade  # noqa: E402
from propex.paths import STATS  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", help="print the box score for one game id and stop")
    args = ap.parse_args()
    games = pl.read_csv(STATS / "games.csv", infer_schema_length=0)
    by_id = {g["game_id"]: g for g in games.iter_rows(named=True)}

    if args.check:
        box, source = grade.box_score(by_id[args.check])
        print(f"source: {source}")
        for name, s in sorted((box or {}).items(), key=lambda kv: -max(kv[1].values()))[:15]:
            print(f"  {name:<24} {s}")
        return

    graded = grade.run(by_id)
    s = grade.load_json(grade.SUMMARY, {})["overall"]
    print(f"graded {len(graded)} game(s). Portfolio: {s['wins']}-{s['losses']}-{s['pushes']}, "
          f"{s['units']:+.2f} units")


if __name__ == "__main__":
    main()
