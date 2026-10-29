"""Pull stats from nflverse and boil them down to the tables the model uses.

Outputs (all in data/stats/):
  games.csv         every game this season, with kickoff, roof, rest days, Vegas lines
  player_games.csv  one row per player per game: usage + efficiency
  team_games.csv    one row per team per game: pace and pass tendencies
  players.csv       current rosters with positions and birthdates
"""

import nflreadpy as nfl
import polars as pl

from propex import config
from propex.paths import STATS, save_csv


def build_games():
    s = nfl.load_schedules(config.SEASON)
    return s.select(
        "game_id", "season", "week", "game_type", "gameday", "weekday", "gametime",
        "away_team", "home_team", "away_score", "home_score",
        "away_rest", "home_rest", "spread_line", "total_line", "div_game",
        "roof", "stadium_id", "stadium", "location", "espn",
    )


def _snap_shares(rosters):
    """Offense snap share per player per game, keyed by gsis player id."""
    snaps = nfl.load_snap_counts(config.SEASON)
    ids = rosters.select("pfr_id", "gsis_id").drop_nulls().unique("pfr_id")
    return (
        snaps.join(ids, left_on="pfr_player_id", right_on="pfr_id", how="inner")
        .select(
            pl.col("gsis_id").alias("player_id"), "game_id",
            pl.col("offense_snaps"), pl.col("offense_pct").alias("snap_share"),
        )
        .unique(["player_id", "game_id"])
    )


def _pbp_usage(pbp):
    """Red-zone touches and success rates per player per game."""
    plays = pbp.filter(pl.col("play_type").is_in(["pass", "run"]))
    rz = pl.col("yardline_100") <= 20
    targets = (
        plays.filter(pl.col("receiver_player_id").is_not_null())
        .group_by(pl.col("receiver_player_id").alias("player_id"), "game_id")
        .agg(
            rz.sum().alias("rz_targets"),
            pl.col("success").mean().alias("target_success_rate"),
        )
    )
    rushes = (
        plays.filter(pl.col("rusher_player_id").is_not_null() & (pl.col("play_type") == "run"))
        .group_by(pl.col("rusher_player_id").alias("player_id"), "game_id")
        .agg(
            rz.sum().alias("rz_carries"),
            (pl.col("yardline_100") <= 5).sum().alias("goal_line_carries"),
            pl.col("success").mean().alias("rush_success_rate"),
        )
    )
    dropbacks = (
        plays.filter(pl.col("passer_player_id").is_not_null() & (pl.col("qb_dropback") == 1))
        .group_by(pl.col("passer_player_id").alias("player_id"), "game_id")
        .agg(
            pl.len().alias("dropbacks"),
            pl.col("success").mean().alias("dropback_success_rate"),
            pl.col("qb_epa").mean().alias("epa_per_dropback"),
        )
    )
    return targets, rushes, dropbacks


def build_team_games(pbp):
    """Pace (seconds per play in neutral game script) and pass tendencies."""
    plays = (
        pbp.filter(pl.col("play_type").is_in(["pass", "run"]) & pl.col("posteam").is_not_null())
        .sort("game_id", "play_id")
        .with_columns(
            (pl.col("game_seconds_remaining").shift(1).over("game_id", "drive")
             - pl.col("game_seconds_remaining")).alias("secs"),
        )
    )
    neutral = (pl.col("score_differential").abs() <= 7) & (pl.col("qtr") <= 3)
    return (
        plays.group_by("game_id", pl.col("posteam").alias("team"),
                       pl.col("defteam").alias("opponent"), "week")
        .agg(
            pl.len().alias("plays"),
            pl.col("qb_dropback").sum().alias("dropbacks"),
            (pl.col("play_type") == "run").sum().alias("rushes"),
            pl.col("secs").filter(neutral & pl.col("secs").is_between(1, 60)).mean()
              .alias("neutral_secs_per_play"),
            pl.col("pass_oe").filter(neutral).mean().alias("neutral_pass_rate_over_exp"),
            pl.col("epa").mean().alias("off_epa_per_play"),
            pl.col("success").mean().alias("off_success_rate"),
        )
        .sort("week", "team")
    )


def build_player_games(pbp, rosters, team_games):
    ps = nfl.load_player_stats(config.SEASON).filter(
        pl.col("position").is_in(["QB", "RB", "WR", "TE", "FB"])
    )
    base = ps.select(
        "player_id", pl.col("player_display_name").alias("player"), "position",
        "team", pl.col("opponent_team").alias("opponent"), "week", "game_id",
        "attempts", "completions", "passing_yards", "passing_tds", "passing_air_yards",
        "passing_epa", "passing_cpoe", "sacks_suffered",
        "carries", "rushing_yards", "rushing_tds", "rushing_epa",
        "targets", "receptions", "receiving_yards", "receiving_tds",
        "receiving_air_yards", "receiving_epa", "target_share", "air_yards_share", "wopr",
    )
    targets, rushes, dropbacks = _pbp_usage(pbp)
    team = team_games.select("game_id", "team", pl.col("dropbacks").alias("team_dropbacks"),
                             pl.col("rushes").alias("team_rushes"))
    df = (
        base.join(_snap_shares(rosters), on=["player_id", "game_id"], how="left")
        .join(targets, on=["player_id", "game_id"], how="left")
        .join(rushes, on=["player_id", "game_id"], how="left")
        .join(dropbacks, on=["player_id", "game_id"], how="left")
        .join(team, on=["game_id", "team"], how="left")
    )
    # nflverse has no 2026 route data yet, so estimate routes as
    # (share of offensive snaps) x (team dropbacks). Labeled "est" on purpose.
    routes = (pl.col("snap_share").fill_null(0) * pl.col("team_dropbacks")).round(1)
    return df.with_columns(
        routes.alias("routes_est"),
        pl.when(routes > 0).then(pl.col("receiving_yards") / routes).alias("yprr_est"),
        pl.when(pl.col("team_rushes") > 0)
          .then(pl.col("carries") / pl.col("team_rushes")).alias("carry_share"),
        pl.when(pl.col("targets") > 0)
          .then(pl.col("receiving_epa") / pl.col("targets")).alias("epa_per_target"),
        pl.when(pl.col("carries") > 0)
          .then(pl.col("rushing_epa") / pl.col("carries")).alias("epa_per_carry"),
    ).sort("week", "team", "player")


def build_players():
    r = nfl.load_rosters_weekly(config.SEASON)
    latest = r.filter(pl.col("week") == r["week"].max())
    return latest.select(
        pl.col("gsis_id").alias("player_id"), "full_name", "team", "position",
        "depth_chart_position", "status", "birth_date", "years_exp",
        "entry_year", "draft_club", "espn_id",
    ).filter(pl.col("player_id").is_not_null()), r


def run():
    games = build_games()
    pbp = nfl.load_pbp(config.SEASON)
    players, rosters = build_players()
    team_games = build_team_games(pbp)
    player_games = build_player_games(pbp, rosters, team_games)

    save_csv(STATS / "games.csv", games)
    save_csv(STATS / "team_games.csv", team_games)
    save_csv(STATS / "player_games.csv", player_games)
    save_csv(STATS / "players.csv", players)
    weeks = pbp["week"].max()
    print(f"nflverse: {games.height} games, stats through week {weeks}, "
          f"{player_games.height} player-games, {players.height} rostered players")
    return games
