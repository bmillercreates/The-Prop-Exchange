"""Check the projections against what actually happened in past weeks.

For each past week, the model only sees games before that week, then we
compare its projections to the real stats. Prints the average miss and
whether the model runs high or low for each stat.

Usage: python scripts/backtest.py [first_week]
"""

import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from propex.model.project import League, load_inputs, project_game  # noqa: E402
from propex.paths import DATA, ODDS, STATS  # noqa: E402

ACTUAL = {"pass_yds": "passing_yards", "rush_yds": "rushing_yards",
          "rec_yds": "receiving_yards", "receptions": "receptions"}


def main():
    first = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    full = load_inputs(STATS, DATA, ODDS)
    pg, tg, games = full["player_games"], full["team_games"], full["games"]
    rows = []
    for week in range(first, int(pg["week"].max()) + 1):
        data = dict(full)
        data["player_games"] = pg.filter(pl.col("week") < week)
        data["team_games"] = tg.filter(pl.col("week") < week)
        data["league"] = League(data["player_games"], data["team_games"],
                                games.filter(pl.col("week").cast(pl.Int64) < week))
        data["lines"], data["weather"] = {}, {}
        data["injuries"] = data["injuries"].clear()
        actual = pg.filter(pl.col("week") == week)
        for g in games.filter(pl.col("week").cast(pl.Int64) == week).iter_rows(named=True):
            for p in project_game(g, data):
                act = actual.filter(pl.col("player_id") == p["player_id"])
                if act.height == 0:
                    continue  # didn't play; the real run would know from injuries
                a = act.row(0, named=True)
                rows.append({"week": week, "stat": "tds", "pos": p["position"],
                             "proj": p["proj"]["tds"],
                             "actual": int(((a["rushing_tds"] or 0) + (a["receiving_tds"] or 0)) > 0)})
                for stat, col in ACTUAL.items():
                    if stat in p["proj"] and p["proj"][stat] >= 15 if stat != "receptions" else p["proj"].get(stat, 0) >= 2:
                        rows.append({"week": week, "stat": stat, "pos": p["position"],
                                     "proj": p["proj"][stat], "actual": a[col] or 0})
    df = pl.DataFrame(rows)
    print(df.group_by("stat", "pos").agg(
        pl.len().alias("n"), pl.col("proj").mean().round(1).alias("avg_proj"),
        pl.col("actual").mean().round(1).alias("avg_actual"),
        (pl.col("actual") - pl.col("proj")).abs().mean().round(1).alias("avg_miss"),
        ((pl.col("actual") - pl.col("proj")).std() / pl.col("proj").mean()).round(2).alias("cv"),
        pl.corr("proj", "actual").round(2).alias("corr"),
    ).sort("stat", "pos"))
    # Anytime TD: does a "30%" player really score about 30% of the time?
    td = df.filter(pl.col("stat") == "tds").with_columns(
        (1 - (-pl.col("proj")).exp()).alias("prob"))
    print("Anytime TD calibration (model chance vs. how often they scored):")
    print(td.with_columns((pl.col("prob") * 10).floor().alias("bucket"))
          .group_by("bucket").agg(pl.len().alias("n"), pl.col("prob").mean().round(3).alias("model"),
                                  pl.col("actual").mean().round(3).alias("scored"))
          .sort("bucket"))


if __name__ == "__main__":
    main()
