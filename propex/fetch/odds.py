"""Sportsbook lines from The Odds API, kept inside the free 500 credits a month.

Budget rules:
  - Listing games is free.
  - Spreads + totals for the whole slate: 2 credits, at most once a day.
  - Player props: 5 credits per game, pulled once, on the morning of game day.
  - Nothing is pulled if fewer than MIN_CREDITS_LEFT credits remain.

Outputs:
  data/odds/events.json       upcoming games with Odds API ids, matched to nflverse ids
  data/odds/lines.json        spreads and totals per game
  data/odds/props/<game>.json player prop lines for one game
  data/odds/credits.json      credits left, and a log of every paid call
"""

import os
from datetime import datetime

import nflreadpy as nfl
import requests

from propex import config
from propex.paths import ET, ODDS, PROPS, load_json, now_et, save_json

CREDITS = ODDS / "credits.json"


class OutOfCredits(Exception):
    pass


def _key():
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        raise RuntimeError("ODDS_API_KEY is not set")
    return key


def _get(path, paid, **params):
    credits = load_json(CREDITS, {"remaining": None, "log": []})
    if paid and credits["remaining"] is not None and credits["remaining"] < config.MIN_CREDITS_LEFT:
        raise OutOfCredits(f"only {credits['remaining']} credits left, skipping {path}")
    r = requests.get(f"{config.ODDS_API_BASE}{path}",
                     params={"apiKey": _key(), **params}, timeout=30)
    r.raise_for_status()
    if "x-requests-remaining" in r.headers:
        credits["remaining"] = int(float(r.headers["x-requests-remaining"]))
    used = int(float(r.headers.get("x-requests-last", 0)))
    if used:
        credits["log"] = (credits["log"] + [
            {"at": now_et().isoformat(timespec="minutes"), "call": path.split("/")[-1],
             "markets": params.get("markets"), "cost": used}
        ])[-300:]
    save_json(CREDITS, credits)
    return r.json()


def _team_abbr():
    teams = nfl.load_teams()
    return dict(zip(teams["team_name"], teams["team_abbr"]))


def _match_game_id(event, games_by_teams, abbr):
    kickoff = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00")).astimezone(ET)
    key = (abbr.get(event["away_team"]), abbr.get(event["home_team"]), kickoff.date().isoformat())
    return games_by_teams.get(key), kickoff


def pull_events(games):
    """Free call. Links each Odds API event to its nflverse game_id."""
    abbr = _team_abbr()
    by_teams = {(g["away_team"], g["home_team"], g["gameday"]): g["game_id"] for g in games}
    events = []
    for ev in _get(f"/sports/{config.ODDS_SPORT}/events", paid=False):
        game_id, kickoff = _match_game_id(ev, by_teams, abbr)
        events.append({"event_id": ev["id"], "game_id": game_id,
                       "away": ev["away_team"], "home": ev["home_team"],
                       "kickoff_et": kickoff.isoformat()})
    save_json(ODDS / "events.json", events)
    return events


def pull_lines(events):
    """Spreads + totals for every upcoming game in one call (2 credits)."""
    lines = load_json(ODDS / "lines.json", {})
    if lines.get("_pulled_on") == now_et().date().isoformat():
        print("odds: game lines already pulled today, reusing them")
        return lines
    data = _get(f"/sports/{config.ODDS_SPORT}/odds", paid=True,
                markets=",".join(config.GAME_LINE_MARKETS),
                bookmakers=config.ODDS_BOOKMAKERS, oddsFormat="american")
    by_event = {e["event_id"]: e["game_id"] for e in events}
    lines = {"_pulled_on": now_et().date().isoformat()}
    for ev in data:
        game_id = by_event.get(ev["id"])
        if not game_id:
            continue
        entry = {}
        for book in ev.get("bookmakers", []):
            for m in book["markets"]:
                for o in m["outcomes"]:
                    entry.setdefault(book["key"], {}).setdefault(m["key"], {})[o["name"]] = {
                        "point": o.get("point"), "price": o["price"]}
        lines[game_id] = entry
    save_json(ODDS / "lines.json", lines)
    return lines


def _flatten_props(data):
    rows = []
    for book in data.get("bookmakers", []):
        for m in book["markets"]:
            for o in m["outcomes"]:
                rows.append({
                    "book": book["key"], "market": m["key"],
                    "player": o.get("description"), "side": o["name"],
                    "line": o.get("point"), "price": o["price"],
                })
    return rows


def pull_props(events, game_ids=None):
    """Props for games kicking off later today that haven't been pulled yet.

    game_ids limits the pull to specific games (used by the pre-kickoff runs).
    """
    now = now_et()
    pulled = []
    for ev in events:
        if not ev["game_id"] or (game_ids and ev["game_id"] not in game_ids):
            continue
        kickoff = datetime.fromisoformat(ev["kickoff_et"])
        if kickoff.date() != now.date() or kickoff <= now:
            continue
        path = PROPS / f"{ev['game_id']}.json"
        if path.exists():
            continue  # once per game, to stay inside the free plan
        data = _get(f"/sports/{config.ODDS_SPORT}/events/{ev['event_id']}/odds", paid=True,
                    markets=",".join(config.PROP_MARKETS),
                    bookmakers=config.ODDS_BOOKMAKERS, oddsFormat="american")
        save_json(path, {"game_id": ev["game_id"], "pulled_at": now.isoformat(timespec="minutes"),
                         "props": _flatten_props(data)})
        pulled.append(ev["game_id"])
    return pulled


def run(games, with_lines=True, game_ids=None):
    try:
        events = pull_events(games)
        if with_lines:
            pull_lines(events)
        pulled = pull_props(events, game_ids)
    except OutOfCredits as exc:
        print(f"odds: stopped to protect the free plan: {exc}")
        return
    left = load_json(CREDITS, {}).get("remaining")
    print(f"odds: {len(events)} upcoming games, props pulled for "
          f"{', '.join(pulled) or 'no new games'}, {left} credits left this month")
