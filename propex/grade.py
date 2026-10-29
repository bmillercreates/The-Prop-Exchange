"""Log and grade picks, and total up Portfolio Performance.

Every pick on a finished game's card goes into data/portfolio/ledger.json
(normally the FINAL card; if a pre-kickoff run never happened, the last
PRELIMINARY card is used and the entry says so). Each pick is graded against the
box score:

  win   +payout on a 1-unit bet (e.g. +0.91 units at -110, +3.80 at +380)
  loss  -1 unit
  push  0 (landed exactly on the line)
  void  0 (player didn't play), shown but left out of the record

Box scores come from ESPN right after the game, with nflverse (usually
updated overnight) as the backup.
"""

from datetime import datetime

import requests

from propex.model.probability import american_to_decimal
from propex.model.project import norm_name
from propex.paths import DATA, ET, load_json, now_et, save_json

LEDGER = DATA / "portfolio" / "ledger.json"
SUMMARY = DATA / "portfolio" / "summary.json"
ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"
STAT_OF = {
    "player_pass_yds": "pass_yds", "player_rush_yds": "rush_yds",
    "player_reception_yds": "rec_yds", "player_receptions": "receptions",
    "player_anytime_td": "tds",
}
TIERS = ["Blue Chip", "Penny Stock", "ETF"]


# ---------- box scores ----------

def _espn_box(espn_id):
    """{normalized name: stats} from ESPN, or None if the game isn't final yet."""
    r = requests.get(ESPN_SUMMARY, params={"event": espn_id}, timeout=30)
    r.raise_for_status()
    data = r.json()
    status = (data.get("header", {}).get("competitions") or [{}])[0].get("status", {})
    if not status.get("type", {}).get("completed"):
        return None
    box = {}
    for team in data.get("boxscore", {}).get("players", []):
        for cat in team.get("statistics", []):
            keys = cat.get("keys", [])
            for a in cat.get("athletes", []):
                name = norm_name(a.get("athlete", {}).get("displayName"))
                vals = dict(zip(keys, a.get("stats", [])))
                p = box.setdefault(name, {"pass_yds": 0, "rush_yds": 0, "rec_yds": 0,
                                          "receptions": 0, "tds": 0})

                def num(key):
                    try:
                        return float(vals.get(key, 0) or 0)
                    except ValueError:
                        return 0.0
                if cat.get("name") == "passing":
                    p["pass_yds"] = num("passingYards")
                elif cat.get("name") == "rushing":
                    p["rush_yds"] = num("rushingYards")
                    p["tds"] += num("rushingTouchdowns")
                elif cat.get("name") == "receiving":
                    p["rec_yds"] = num("receivingYards")
                    p["receptions"] = num("receptions")
                    p["tds"] += num("receivingTouchdowns")
                elif cat.get("name") in ("kickReturns", "puntReturns", "fumbles", "defensive",
                                         "interceptions"):
                    for k in ("kickReturnTouchdowns", "puntReturnTouchdowns",
                              "fumbleRecoveryTouchdowns", "defensiveTouchdowns",
                              "interceptionTouchdowns"):
                        p["tds"] += num(k)
    return box


def _nflverse_box(game_id):
    import nflreadpy as nfl
    import polars as pl

    season = int(game_id.split("_")[0])
    ps = nfl.load_player_stats(season).filter(pl.col("game_id") == game_id)
    if ps.height == 0:
        return None
    box = {}
    for r in ps.iter_rows(named=True):
        box[norm_name(r["player_display_name"])] = {
            "pass_yds": r["passing_yards"] or 0, "rush_yds": r["rushing_yards"] or 0,
            "rec_yds": r["receiving_yards"] or 0, "receptions": r["receptions"] or 0,
            "tds": (r["rushing_tds"] or 0) + (r["receiving_tds"] or 0)
                   + (r["special_teams_tds"] or 0),
        }
    return box


def box_score(game):
    """(box, source) for a finished game, or (None, reason) if not available yet."""
    if game.get("espn"):
        try:
            box = _espn_box(game["espn"])
            if box:
                return box, "espn"
        except Exception as exc:
            print(f"grade: ESPN box score failed for {game['game_id']} ({exc}), trying nflverse")
    try:
        box = _nflverse_box(game["game_id"])
        if box:
            return box, "nflverse"
    except Exception as exc:
        print(f"grade: nflverse box score failed for {game['game_id']} ({exc})")
    return None, "not final yet"


# ---------- grading ----------

def grade_leg(pick, box):
    stats = box.get(norm_name(pick["player"]))
    if stats is None:
        return "void", None
    actual = stats[STAT_OF[pick["market"]]]
    if pick["market"] == "player_anytime_td":
        return ("win" if actual >= 1 else "loss"), actual
    if actual == pick["line"]:
        return "push", actual
    over = actual > pick["line"]
    return ("win" if over == (pick["side"] == "Over") else "loss"), actual


def _units(result, price):
    return {"win": american_to_decimal(price) - 1, "loss": -1.0}.get(result, 0.0)


def log_and_grade(card, box, source):
    """Ledger entries for one finished game's card."""
    entries, graded_at = [], now_et().isoformat(timespec="minutes")
    base = {"game_id": card["game_id"], "matchup": f"{card['away']} @ {card['home']}",
            "kickoff": card["kickoff"], "card_status": card["status"],
            "graded_at": graded_at, "source": source}
    for p in card["blue_chips"] + card["penny_stocks"]:
        result, actual = grade_leg(p, box)
        entries.append({**base, "tier": p["tier"], "title": p["title"], "player": p["player"],
                        "market": p["market"], "side": p["side"], "line": p["line"],
                        "price": p["price"], "edge": p["edge"], "actual": actual,
                        "result": result, "units": round(_units(result, p["price"]), 3)})
    for e in card["etfs"]:
        legs = [(leg, *grade_leg(leg, box)) for leg in e["legs"]]
        results = [r for _, r, _ in legs]
        if "loss" in results:
            result = "loss"
        elif "void" in results:
            result = "void"
        elif all(r == "win" for r in results):
            result = "win"
        else:
            result = "push"
        entries.append({**base, "tier": "ETF", "title": " + ".join(leg["title"] for leg in e["legs"]),
                        "player": " / ".join(leg["player"] for leg in e["legs"]),
                        "market": "parlay", "side": "Over", "line": None, "price": e["price"],
                        "edge": e["edge"], "actual": [a for _, _, a in legs],
                        "leg_results": results, "result": result,
                        "units": round(_units(result, e["price"]), 3)})
    return entries


def summarize(ledger):
    def block(rows):
        counted = [r for r in rows if r["result"] in ("win", "loss", "push")]
        w = sum(r["result"] == "win" for r in counted)
        l_ = sum(r["result"] == "loss" for r in counted)
        p = sum(r["result"] == "push" for r in counted)
        units = round(sum(r["units"] for r in counted), 2)
        risked = len(counted)
        return {"wins": w, "losses": l_, "pushes": p, "units": units,
                "roi": round(units / risked, 4) if risked else None,
                "hit_rate": round(w / (w + l_), 4) if w + l_ else None, "bets": risked}

    by_day, running = {}, 0.0
    for r in sorted(ledger, key=lambda r: r["kickoff"]):
        if r["result"] in ("win", "loss", "push"):
            running += r["units"]
            by_day[r["kickoff"][:10]] = round(running, 2)
    return {
        "updated_at": now_et().isoformat(timespec="minutes"),
        "overall": block(ledger),
        "tiers": {t: block([r for r in ledger if r["tier"] == t]) for t in TIERS},
        "curve": [{"date": d, "units": u} for d, u in by_day.items()],
        "recent": sorted(ledger, key=lambda r: (r["kickoff"], r["tier"]), reverse=True)[:30],
    }


def run(games_by_id):
    """Grade every card whose game has finished and isn't in the ledger yet."""
    ledger = load_json(LEDGER, [])
    done = {r["game_id"] for r in ledger}
    now = datetime.now(ET)
    graded = []
    for card_path in sorted((DATA / "picks").glob("*.json")):
        card = load_json(card_path)
        gid = card["game_id"]
        if gid in done or not (card["blue_chips"] or card["penny_stocks"] or card["etfs"]):
            continue
        kickoff = datetime.fromisoformat(card["kickoff"]).replace(tzinfo=ET)
        if (now - kickoff).total_seconds() < 3 * 3600:
            continue  # can't be over yet
        box, source = box_score(games_by_id[gid])
        if box is None:
            print(f"grade: {gid} {source}")
            continue
        entries = log_and_grade(card, box, source)
        ledger += entries
        graded.append(gid)
        wins = sum(e["result"] == "win" for e in entries)
        print(f"grade: {gid} from {source}: {wins}/{len(entries)} won, "
              f"{sum(e['units'] for e in entries):+.2f} units")
    save_json(LEDGER, ledger)
    save_json(SUMMARY, summarize(ledger))
    return graded
