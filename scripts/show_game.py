"""Print a plain-text snapshot of everything we have for one game.

Usage: python scripts/show_game.py [game_id]
With no game_id, shows the next game that hasn't kicked off.
"""

import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from propex.paths import DATA, ODDS, PROPS, STATS, load_json, now_et  # noqa: E402

MARKET_NAMES = {
    "player_pass_yds": "Pass yds", "player_rush_yds": "Rush yds",
    "player_reception_yds": "Rec yds", "player_receptions": "Receptions",
    "player_anytime_td": "Anytime TD",
}


def pick_game(games, game_id):
    if game_id:
        return games.filter(pl.col("game_id") == game_id).row(0, named=True)
    now = now_et().strftime("%Y-%m-%d %H:%M")
    upcoming = games.filter((pl.col("gameday") + " " + pl.col("gametime")) > now)
    return upcoming.sort("gameday", "gametime").row(0, named=True)


def team_usage(pg, team, last_n=4):
    weeks = sorted(pg.filter(pl.col("team") == team)["week"].unique())[-last_n:]
    recent = pg.filter((pl.col("team") == team) & pl.col("week").is_in(weeks))
    return (
        recent.group_by("player", "position")
        .agg(
            pl.col("snap_share").mean().alias("snap"),
            pl.col("target_share").mean().alias("tgt_share"),
            pl.col("air_yards_share").mean().alias("air_share"),
            pl.col("carry_share").mean().alias("carry_share"),
            (pl.col("rz_targets").fill_null(0) + pl.col("rz_carries").fill_null(0)).sum().alias("rz"),
            pl.col("passing_yards").mean().alias("pass_yds"),
            pl.col("passing_cpoe").mean().alias("cpoe"),
            pl.col("epa_per_dropback").mean().alias("epa_db"),
            pl.col("rushing_yards").mean().alias("rush_yds"),
            pl.col("receiving_yards").mean().alias("rec_yds"),
            pl.col("receptions").mean().alias("rec"),
            pl.col("yprr_est").mean().alias("yprr"),
        )
        # starting QB first, then whoever gets the most targets or carries
        .filter((pl.col("position") != "QB") | (pl.col("snap") >= 0.5))
        .with_columns(pl.max_horizontal(
            pl.col("tgt_share").fill_null(0), pl.col("carry_share").fill_null(0),
            (pl.col("position") == "QB").cast(pl.Float64)).alias("_rank"))
        .sort("_rank", descending=True)
        .head(7)
    ), weeks


def pct(x):
    return "  -  " if x is None else f"{x * 100:4.0f}%"


def num(x, fmt="{:5.1f}"):
    return "  -  " if x is None else fmt.format(x)


def main():
    games = pl.read_csv(STATS / "games.csv", infer_schema_length=0)
    g = pick_game(games, sys.argv[1] if len(sys.argv) > 1 else None)
    gid, away, home = g["game_id"], g["away_team"], g["home_team"]
    out = [f"### SAMPLE GAME: {away} @ {home} ({gid})",
           "```",
           f"Kickoff: {g['weekday']} {g['gameday']} {g['gametime']} ET at {g['stadium']}",
           f"Rest days: {away} {g['away_rest']}, {home} {g['home_rest']}"]

    lines = load_json(ODDS / "lines.json", {}).get(gid, {})
    book = lines.get("draftkings") or next(iter(lines.values()), None)
    if book:
        spreads = book.get("spreads", {})
        totals = book.get("totals", {})
        sp_txt = ", ".join(f"{t} {v['point']:+g}" for t, v in spreads.items())
        tot = totals.get("Over", {}).get("point")
        out.append(f"Sportsbook: {sp_txt}; total {tot}")
    else:
        out.append(f"Lines (nflverse): {home} by {g['spread_line']}, total {g['total_line']}")

    w = load_json(DATA / "weather.json", {}).get(gid)
    if not w:
        out.append("Weather: not available yet (forecasts start 14 days out)")
    elif w.get("covered"):
        out.append("Weather: indoors / roof closed, not a factor")
    elif "error" in w:
        out.append(f"Weather: lookup failed ({w['error']})")
    else:
        out.append(f"Weather: {w['temp_f']}F, wind {w['wind_mph']} mph (gusts {w['gust_mph']}), "
                   f"{w['precip_chance']}% chance of rain/snow")

    tg = pl.read_csv(STATS / "team_games.csv")
    for team in (away, home):
        t = tg.filter(pl.col("team") == team)
        out.append(f"{team} pace: {t['neutral_secs_per_play'].mean():.1f} sec/play (neutral), "
                   f"pass rate vs expected {t['neutral_pass_rate_over_exp'].mean():+.1f}%, "
                   f"offense EPA/play {t['off_epa_per_play'].mean():+.3f}")

    inj = pl.read_csv(DATA / "injuries.csv", infer_schema_length=0) if (DATA / "injuries.csv").exists() else None
    pg = pl.read_csv(STATS / "player_games.csv", infer_schema_length=5000)
    for team in (away, home):
        usage, weeks = team_usage(pg, team)
        out.append("")
        out.append(f"{team} key players, avg of weeks {weeks[0]}-{weeks[-1]}:")
        out.append("  Player                 Pos Snap  Tgt%  Air%  Car%  RZ  PassY  CPOE RushY  RecY  Rec  YPRR*")
        for r in usage.iter_rows(named=True):
            out.append(
                f"  {r['player'][:22]:<22} {r['position']:<3}{pct(r['snap'])}{pct(r['tgt_share'])}"
                f"{pct(r['air_share'])}{pct(r['carry_share'])} {r['rz']:>3} "
                f"{num(r['pass_yds'], '{:6.0f}')}{num(r['cpoe'], '{:+6.1f}')}"
                f"{num(r['rush_yds'], '{:6.0f}')}{num(r['rec_yds'], '{:6.0f}')}"
                f"{num(r['rec'], '{:5.1f}')}{num(r['yprr'], '{:6.2f}')}")
        if inj is not None:
            hurt = inj.filter((pl.col("team") == team) & pl.col("status").is_in(
                ["Out", "Doubtful", "Questionable", "Injured Reserve"]))
            names = [f"{r['player']} ({r['position']}, {r['status']})"
                     for r in hurt.filter(pl.col("position").is_in(["QB", "RB", "WR", "TE"])).iter_rows(named=True)]
            out.append(f"  Injuries (skill players): {'; '.join(names) or 'none listed'}")

    props = load_json(PROPS / f"{gid}.json")
    out.append("")
    if not props:
        out.append("Player props: not pulled yet (pulled once, on the morning of game day)")
    else:
        rows = [p for p in props["props"] if p["book"] == "draftkings"] or props["props"]
        out.append(f"Player props pulled {props['pulled_at']}: {len(props['props'])} prices. "
                   "A few DraftKings lines:")
        shown = {}
        for p in rows:
            if p["side"] not in ("Over", "Yes"):
                continue
            if shown.get(p["market"], 0) >= 3:
                continue
            shown[p["market"]] = shown.get(p["market"], 0) + 1
            line = f"o{p['line']}" if p["line"] is not None else "yes"
            out.append(f"  {MARKET_NAMES.get(p['market'], p['market']):<11} {p['player']:<24} "
                       f"{line:<7} {p['price']:+d}")
    credits = load_json(ODDS / "credits.json", {}).get("remaining")
    out.append(f"\nOdds API credits left this month: {credits}")
    out.append("* YPRR is estimated: nflverse has no 2026 route data, so routes ~ snap share x team dropbacks.")
    out.append("```")
    print("\n".join(out))


if __name__ == "__main__":
    main()
