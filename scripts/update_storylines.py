"""Build this week's Storylines (run after the model, which supplies projections)."""

import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from propex import storylines  # noqa: E402
from propex.paths import STATS, now_et  # noqa: E402

games = pl.read_csv(STATS / "games.csv", infer_schema_length=0)
today = now_et().date().isoformat()
upcoming = games.filter(pl.col("gameday") >= today)
week = upcoming.sort("gameday")["week"].head(1).to_list()
storylines.run(upcoming.filter(pl.col("week").is_in(week)).to_dicts())
