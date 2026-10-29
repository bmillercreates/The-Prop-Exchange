"""Project each player's stats for one game.

Order of operations (matches the plan Brayden laid out):
  1. Team volume: how many plays, and how many of them are passes, from pace,
     the Vegas total and spread (game script), and weather.
  2. Usage: each player's share of targets, carries and red-zone chances,
     weighting the last 4 games more than the rest of the season.
  3. Efficiency: yards per target / carry / attempt, pulled toward the
     position average so a few big games don't dominate.
  4. Adjustments: opponent defense vs. the position, weather, rest/travel,
     and teammates who are out (their share goes to everyone else).
"""

from datetime import datetime

import polars as pl

RECENT_GAMES = 4
RECENCY_DECAY = 0.85       # each older game counts 15% less than the one after it
RECENT_WEIGHT = 0.6        # team-level stats: last 4 games 60%, full season 40%
OUT_STATUSES = {"Out", "Doubtful", "Injured Reserve", "Suspension",
                "Physically Unable to Perform", "Reserve/Non-Football Injury"}
WEST_TEAMS = {"SEA", "SF", "LA", "LAC", "LV", "ARI"}
PTS_PER_TD = 9.5           # teams score about one offensive TD per 9.5 points

# Shrinkage: how many "average" opportunities to blend in with a player's own
SHRINK = {"targets": 30, "carries": 40, "attempts": 120, "defense_games": 4}


def norm_name(name):
    name = (name or "").lower().replace(".", "").replace("'", "").replace("-", " ")
    parts = [p for p in name.split() if p not in {"jr", "sr", "ii", "iii", "iv", "v"}]
    return " ".join(parts)


def _blend(recent, season):
    if recent is None:
        return season
    if season is None:
        return recent
    return RECENT_WEIGHT * recent + (1 - RECENT_WEIGHT) * season


def _shrink(total, opportunities, prior_rate, k):
    return (total + prior_rate * k) / (opportunities + k)


class League:
    """League-wide averages used as baselines and for shrinkage."""

    def __init__(self, pg, tg, games):
        played = games.filter(pl.col("home_score").is_not_null())
        self.total = float(played.select((pl.col("home_score") + pl.col("away_score")).mean()).item())
        self.plays = tg["plays"].mean()
        self.secs = tg["neutral_secs_per_play"].mean()
        self.pass_rate = (tg["dropbacks"].sum() / tg["plays"].sum())
        team_att = pg.group_by("game_id", "team").agg(pl.col("attempts").sum())
        self.att_per_dropback = team_att["attempts"].sum() / tg["dropbacks"].sum()
        self.rate = {}
        for pos in ("QB", "RB", "WR", "TE"):
            p = pg.filter(pl.col("position") == pos)
            tgt, car, att = p["targets"].sum(), p["carries"].sum(), p["attempts"].sum()
            self.rate[pos] = {
                "catch": p["receptions"].sum() / tgt if tgt else 0.65,
                "ypt": p["receiving_yards"].sum() / tgt if tgt else 7.5,
                "ypc": p["rushing_yards"].sum() / car if car else 4.2,
                "ypa": p["passing_yards"].sum() / att if att else 6.8,
            }
        self.defense_table = self._defense_factors(pg)

    @staticmethod
    def _defense_factors(pg):
        """How much each defense allows to each position vs. league average."""
        stats = {"rec_yds": "receiving_yards", "receptions": "receptions",
                 "rush_yds": "rushing_yards", "pass_yds": "passing_yards"}
        per_game = pg.group_by("game_id", "opponent", "position").agg(
            [pl.col(c).sum().alias(s) for s, c in stats.items()])
        out = {}
        k = SHRINK["defense_games"]
        for stat in stats:
            league = per_game.group_by("position").agg(pl.col(stat).mean().alias("lg"))
            agg = per_game.group_by("opponent", "position").agg(
                pl.col(stat).sum().alias("tot"), pl.len().alias("n"))
            for r in agg.join(league, on="position").iter_rows(named=True):
                if not r["lg"]:
                    continue
                f = (r["tot"] + r["lg"] * k) / (r["n"] + k) / r["lg"]
                out[(stat, r["opponent"], r["position"])] = min(max(f, 0.8), 1.2)
        return out

    def defense(self, stat, opponent, position):
        return self.defense_table.get((stat, opponent, position), 1.0)


def _team_context(team, opp, game, lines, weather, tg, league, is_home):
    """Plays, pass/rush split and efficiency multipliers for one offense."""
    t = tg.filter(pl.col("team") == team).sort("week")
    o = tg.filter(pl.col("opponent") == opp).sort("week")  # what opp's defense faces

    def blended(df, col):
        recent = df.tail(RECENT_GAMES)[col].mean()
        return _blend(recent, df[col].mean())

    total, home_margin = lines
    margin = home_margin if is_home else -home_margin       # >0 means favored
    implied_pts = total / 2 + margin / 2

    # Pace: half from this offense's snap volume, half from what the opposing
    # defense usually faces, pulled 30% toward league average (small samples)
    plays = 0.5 * blended(t, "plays") + 0.5 * blended(o, "plays")
    plays = 0.7 * plays + 0.3 * league.plays
    plays *= (total / league.total) ** 0.3
    pace_secs = (blended(t, "neutral_secs_per_play") + blended(o, "neutral_secs_per_play")) / 2

    pass_rate = (t.tail(RECENT_GAMES)["dropbacks"].sum() / t.tail(RECENT_GAMES)["plays"].sum())
    pass_rate = _blend(pass_rate, t["dropbacks"].sum() / t["plays"].sum())
    pass_rate -= 0.007 * margin   # favorites lean on the run, underdogs throw to catch up

    pass_eff, notes = 1.0, []
    if weather and not weather.get("covered") and "wind_mph" in weather:
        wind = weather["wind_mph"]
        if wind >= 15:
            pass_eff *= max(0.85, 1 - 0.01 * (wind - 10))
            pass_rate -= 0.02
            notes.append(f"wind {wind} mph")
        if weather.get("precip_in", 0) >= 0.05 or weather.get("precip_chance", 0) >= 60:
            pass_eff *= 0.97
            notes.append("rain/snow expected")
    pass_rate = min(max(pass_rate, 0.40), 0.75)

    rest = int(game["home_rest" if is_home else "away_rest"] or 7)
    eff = 1.0
    if rest <= 5:
        eff *= 0.98
        notes.append("short week")
    elif rest >= 13:
        eff *= 1.02
        notes.append("coming off a bye")
    kickoff_hour = int(str(game["gametime"]).split(":")[0])
    if team in WEST_TEAMS and not is_home and game["home_team"] not in WEST_TEAMS and kickoff_hour <= 13:
        eff *= 0.97
        notes.append("West Coast team in an early East kickoff")

    dropbacks = plays * pass_rate
    return {
        "plays": plays, "dropbacks": dropbacks,
        "pass_att": dropbacks * league.att_per_dropback,
        "rushes": plays - dropbacks,
        "implied_pts": implied_pts, "margin": margin,
        "pass_eff": pass_eff * eff, "rush_eff": eff,
        "notes": notes, "pace_secs": pace_secs,
    }


def _player_usage(pg, team, roster_ids, is_out):
    """Usage shares and efficiency totals for each player on the roster.

    A player's share is his average role in the games he played, where each
    game's weight drops 15% per week of age (so the last 3-4 games carry about
    half the weight) and halves for every key teammate who sat out that game.
    Shares are then scaled so the whole roster adds up to the team's usual
    total. This way a starter returning from injury isn't buried by the weeks
    he missed, and his fill-ins don't keep the bigger role they had meanwhile.

    is_out(player_id, name) says whether a player is out for this game.
    """
    df = pg.filter((pl.col("team") == team) & pl.col("player_id").is_in(roster_ids))
    team_weeks = sorted(df["week"].unique())
    if not team_weeks:
        return {}
    team_rz = df.group_by("week").agg(
        (pl.col("rz_targets").fill_null(0) + pl.col("rz_carries").fill_null(0)).sum().alias("rz_team"),
        (pl.col("receiving_tds") + pl.col("rushing_tds")).sum().alias("td_team"))
    df = df.join(team_rz, on="week", how="left").with_columns(
        ((pl.col("rz_targets").fill_null(0) + pl.col("rz_carries").fill_null(0))
         / pl.col("rz_team")).fill_nan(0).fill_null(0).alias("rz_share"),
        ((pl.col("receiving_tds") + pl.col("rushing_tds")) / pl.col("td_team"))
        .fill_nan(0).fill_null(0).alias("td_share"),
    )

    # Key players available this week: meaningful role when they do play
    when_active = df.group_by("player_id", "player").agg(
        pl.max_horizontal(pl.col("target_share").fill_null(0).mean(),
                          pl.col("carry_share").fill_null(0).mean()).alias("role"),
        pl.col("week").max().alias("last_week"))
    key = {r["player_id"] for r in when_active.iter_rows(named=True)
           if r["role"] >= 0.10 and not is_out(r["player_id"], r["player"])
           and team_weeks[-1] - r["last_week"] < 3}
    active = {w: set(df.filter(pl.col("week") == w)["player_id"]) for w in team_weeks}
    weights = {}
    for age, w in enumerate(reversed(team_weeks)):
        weights[w] = RECENCY_DECAY ** age * 0.5 ** len(key - active[w])
    recent_weeks = team_weeks[-RECENT_GAMES:]
    # What the roster's shares usually add up to in a game (e.g. RBs + QB
    # scrambles take ~100% of carries, but some targets go to departed players)
    usual_total = {
        col: df.group_by("week").agg(pl.col(col).fill_null(0).sum())[col].mean()
        for col in ("target_share", "carry_share", "rz_share", "td_share", "air_yards_share")
    }

    out = {}
    for pid, rows in df.group_by("player_id"):
        rows = rows.sort("week")
        recent = rows.filter(pl.col("week").is_in(recent_weeks))
        wk = rows["week"].to_list()
        w_played = sum(weights[w] for w in wk)

        def share(col):
            vals = rows[col].fill_null(0).to_list()
            active_share = sum(weights[w] * v for w, v in zip(wk, vals)) / w_played
            per_team_game = sum(vals) / len(team_weeks)
            # with only a game or two, lean partly on his per-team-game average
            n = len(vals)
            return (n * active_share + per_team_game) / (n + 1)

        last = rows.row(-1, named=True)
        out[pid[0]] = {
            "player_id": pid[0], "player": last["player"], "position": last["position"],
            "games": rows.height, "recent_games": recent.height,
            "snap": share("snap_share"), "target_share": share("target_share"),
            "carry_share": share("carry_share"), "rz_share": share("rz_share"),
            "td_share": share("td_share"), "air_share": share("air_yards_share"),
            "snap_sd": rows["snap_share"].std() or 0.0,
            "targets": rows["targets"].sum(), "receptions": rows["receptions"].sum(),
            "rec_yds": rows["receiving_yards"].sum(), "carries": rows["carries"].sum(),
            "rush_yds": rows["rushing_yards"].sum(), "attempts": rows["attempts"].sum(),
            "pass_yds": rows["passing_yards"].sum(),
            "cpoe": recent["passing_cpoe"].mean() if last["position"] == "QB" else None,
            "epa_db": recent["epa_per_dropback"].mean() if last["position"] == "QB" else None,
            "yprr": recent["yprr_est"].mean(),
            "last_week": last["week"], "team_last_week": team_weeks[-1],
            "out": is_out(pid[0], last["player"]),
        }
    # Scale down when the roster's combined role is bigger than one game holds
    current = [u for u in out.values() if team_weeks[-1] - u["last_week"] < 3]
    for col, key_ in (("target_share", "target_share"), ("carry_share", "carry_share"),
                      ("rz_share", "rz_share"), ("td_share", "td_share"),
                      ("air_yards_share", "air_share")):
        tot = sum(u[key_] for u in current)
        if usual_total[col] and tot > usual_total[col]:
            for u in current:
                u[key_] *= usual_total[col] / tot
    return out


def _redistribute(usage, injured_ids, key, eligible):
    """Give injured players' share of targets/carries to healthy teammates."""
    lost = sum(u[key] for pid, u in usage.items() if pid in injured_ids)
    healthy = {pid: u for pid, u in usage.items()
               if pid not in injured_ids and u["position"] in eligible and u[key] > 0}
    base = sum(u[key] for u in healthy.values())
    if lost <= 0 or base <= 0:
        return 0.0
    for u in healthy.values():
        u[key] += lost * u[key] / base
    return lost


def project_game(game, data):
    """Return a list of player projections for both teams in one game."""
    pg, tg, league = data["player_games"], data["team_games"], data["league"]
    gid = game["game_id"]
    lines = data["lines"].get(gid)
    total, home_margin = float(game["total_line"]), float(game["spread_line"])
    if lines:
        book = lines.get("draftkings") or next(iter(lines.values()))
        total = book.get("totals", {}).get("Over", {}).get("point", total)
        home_spread = book.get("spreads", {}).get(data["team_names"][game["home_team"]], {}).get("point")
        if home_spread is not None:
            home_margin = -home_spread

    weather = data["weather"].get(gid)
    injuries = data["injuries"]
    projections = []
    for team, opp, is_home in ((game["away_team"], game["home_team"], False),
                               (game["home_team"], game["away_team"], True)):
        ctx = _team_context(team, opp, game, (total, home_margin), weather, tg, league, is_home)
        roster = data["players"].filter(pl.col("team") == team)
        hurt = injuries.filter(pl.col("team") == team)
        status = {norm_name(r["player"]): r["status"] for r in hurt.iter_rows(named=True)}
        roster_status = {r["player_id"]: r["status"] for r in roster.iter_rows(named=True)}

        def is_out(pid, name):
            return (status.get(norm_name(name)) in OUT_STATUSES
                    or roster_status.get(pid) in ("RES", "INA", "CUT", "SUS"))

        usage = _player_usage(pg, team, roster["player_id"].to_list(), is_out)
        # Long-absent players (3+ team games missed) are already out of the
        # recent picture: drop them without handing their old role to others.
        for pid in [pid for pid, u in usage.items() if u["team_last_week"] - u["last_week"] >= 3]:
            del usage[pid]
        injured = {pid for pid, u in usage.items() if u["out"]}
        out_names = [usage[pid]["player"] for pid in injured
                     if usage[pid]["target_share"] + usage[pid]["carry_share"] >= 0.08]
        lost_t = _redistribute(usage, injured, "target_share", {"WR", "TE", "RB", "FB"})
        lost_c = _redistribute(usage, injured, "carry_share", {"RB", "FB", "QB", "WR"})
        _redistribute(usage, injured, "rz_share", {"WR", "TE", "RB", "FB", "QB"})
        _redistribute(usage, injured, "td_share", {"WR", "TE", "RB", "FB", "QB"})

        qbs = [u for pid, u in usage.items() if u["position"] == "QB" and pid not in injured]
        starter = max(qbs, key=lambda u: u["snap"], default=None)
        team_tds = ctx["implied_pts"] / PTS_PER_TD

        for pid, u in usage.items():
            if pid in injured or u["games"] == 0:
                continue
            pos = u["position"] if u["position"] != "FB" else "RB"
            if pos == "QB" and u is not starter:
                continue
            r = league.rate[pos]
            p = {"game_id": gid, "team": team, "opponent": opp, "player": u["player"],
                 "player_id": pid, "position": pos, "usage": u, "ctx": ctx,
                 "injury_status": status.get(norm_name(u["player"])),
                 "teammates_out": out_names, "boost_targets": lost_t, "boost_carries": lost_c,
                 "proj": {}, "factors": {}}

            carries = ctx["rushes"] * u["carry_share"]
            ypc = _shrink(u["rush_yds"], u["carries"], r["ypc"], SHRINK["carries"])
            d_rush = league.defense("rush_yds", opp, pos)
            p["proj"]["rush_yds"] = carries * ypc * d_rush * ctx["rush_eff"]
            p["factors"]["rush_yds"] = d_rush

            if pos == "QB":
                ypa = _shrink(u["pass_yds"], u["attempts"], r["ypa"], SHRINK["attempts"])
                d_pass = league.defense("pass_yds", opp, "QB")
                p["proj"]["pass_yds"] = ctx["pass_att"] * ypa * d_pass * ctx["pass_eff"]
                p["proj"]["pass_att"] = ctx["pass_att"]
                p["factors"]["pass_yds"] = d_pass
            else:
                targets = ctx["pass_att"] * u["target_share"]
                catch = _shrink(u["receptions"], u["targets"], r["catch"], SHRINK["targets"])
                ypt = _shrink(u["rec_yds"], u["targets"], r["ypt"], SHRINK["targets"])
                d_rec = league.defense("rec_yds", opp, pos)
                d_recs = league.defense("receptions", opp, pos)
                p["proj"]["targets"] = targets
                p["proj"]["receptions"] = targets * catch * d_recs ** 0.5
                p["proj"]["rec_yds"] = targets * ypt * d_rec * ctx["pass_eff"]
                p["factors"]["rec_yds"] = d_rec
                p["factors"]["receptions"] = d_recs
            p["proj"]["carries"] = carries
            # TD chances: blend of red-zone opportunity share and actual TD share
            # (mostly red-zone opportunity; actual TDs are too random to lean on)
            td_share = 0.8 * u["rz_share"] + 0.2 * u["td_share"]
            if pos == "QB":
                td_share *= 0.5  # QB red-zone touches are mostly passes, not his own TDs
            p["proj"]["tds"] = team_tds * td_share
            projections.append(p)
    return projections


def load_inputs(stats_dir, data_dir, odds_dir):
    from propex.paths import load_json
    import nflreadpy as nfl

    pg = pl.read_csv(stats_dir / "player_games.csv", infer_schema_length=10000)
    tg = pl.read_csv(stats_dir / "team_games.csv")
    games = pl.read_csv(stats_dir / "games.csv", infer_schema_length=0).with_columns(
        pl.col("home_score").cast(pl.Float64), pl.col("away_score").cast(pl.Float64))
    teams = nfl.load_teams()
    league = League(pg, tg, games)
    inj_path = data_dir / "injuries.csv"
    return {
        "player_games": pg, "team_games": tg, "games": games, "league": league,
        "players": pl.read_csv(stats_dir / "players.csv", infer_schema_length=0),
        "injuries": pl.read_csv(inj_path, infer_schema_length=0) if inj_path.exists()
        else pl.DataFrame(schema={"team": pl.Utf8, "player": pl.Utf8, "status": pl.Utf8}),
        "weather": load_json(data_dir / "weather.json", {}),
        "lines": {k: v for k, v in load_json(odds_dir / "lines.json", {}).items() if not k.startswith("_")},
        "team_names": dict(zip(teams["team_abbr"], teams["team_name"])),
        "loaded_at": datetime.now().isoformat(),
    }
