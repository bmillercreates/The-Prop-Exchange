"""Compare projections with sportsbook prices and choose the picks.

Blue Chips    2-3 props with the biggest edge AND stable inputs, normal prices
Penny Stocks  1-2 plus-money props the model likes more than the odds do
ETFs          1-2 two-leg parlays whose legs tend to hit together

"Edge" is the expected return on a $1 bet at the best available price:
model probability x payout - 1. "Prob edge" is model probability minus the
book's fair probability (after removing the book's cut).
"""

import itertools
from collections import defaultdict

from propex.model import probability as P
from propex.model.project import norm_name

MARKETS = {
    "player_pass_yds": ("pass_yds", "passing yards"),
    "player_rush_yds": ("rush_yds", "rushing yards"),
    "player_reception_yds": ("rec_yds", "receiving yards"),
    "player_receptions": ("receptions", "receptions"),
    "player_anytime_td": ("tds", "anytime TD"),
}
TEAM_NICK = {}  # filled from the data: "GB" -> "Packers"

BLUE_MIN_PROB_EDGE = 0.03
# Brayden prefers overs: they get a ranking boost, unders need a bigger edge,
# and at most one under makes the Blue Chips. Penny Stocks and ETFs are overs only.
OVER_BONUS = 0.02
UNDER_MIN_PROB_EDGE = 0.05
MAX_BLUE_UNDERS = 1
BLUE_PRICE_RANGE = (-200, 120)
PENNY_PRICE_RANGE = (130, 450)  # real upside, not lottery tickets
PENNY_MIN_EDGE = 0.05
MAX_DISAGREEMENT = 0.30   # model this far from the line usually means missing info
ETF_RHO = 0.35            # how strongly QB yards and his receiver's yards move together
SGP_MARGIN = 1.12         # typical sportsbook cut on a same-game parlay


def _best_offers(props):
    """For each player/market/side, every book's price with its fair probability."""
    by_key = defaultdict(list)
    pairs = defaultdict(dict)
    for p in props:
        pairs[(p["book"], p["market"], p["player"], p["line"])][p["side"]] = p["price"]
    for (book, market, player, line), sides in pairs.items():
        for side, price in sides.items():
            if market == "player_anytime_td":
                fair = P.american_to_prob(price) / P.TD_MARGIN
            elif "Over" in sides and "Under" in sides:
                fair_over = P.no_vig(sides["Over"], sides["Under"])
                fair = fair_over if side == "Over" else 1 - fair_over
            else:
                continue
            by_key[(norm_name(player), market, side)].append(
                {"book": book, "line": line, "price": price, "fair": fair, "player": player})
    return by_key


def _stability(p, stat, line):
    """Reasons this pick is shaky (empty list = stable)."""
    u, flags = p["usage"], []
    if u["games"] < 4:
        flags.append(f"only {u['games']} games of data")
    if u["recent_games"] < 3:
        flags.append("missed recent games")
    if u["snap_sd"] > 0.15:
        flags.append("playing time has swung a lot")
    if p["injury_status"] == "Questionable":
        flags.append("listed Questionable")
    if stat != "tds" and line:
        mean = p["proj"][stat]
        if abs(mean - line) / max(line, 10) > MAX_DISAGREEMENT:
            flags.append("model is far from the market")
    return flags


def build_candidates(projections, props):
    offers = _best_offers(props)
    cands = []
    for p in projections:
        for market, (stat, label) in MARKETS.items():
            if stat not in p["proj"]:
                continue
            for side in ("Over", "Under", "Yes"):
                options = offers.get((norm_name(p["player"]), market, side))
                if not options:
                    continue
                best = None
                for o in options:
                    if stat == "tds":
                        prob = P.prob_anytime_td(p["proj"]["tds"])
                    else:
                        over = P.prob_over(stat, p["position"], p["proj"][stat], o["line"])
                        prob = over if side == "Over" else 1 - over
                    raw = prob
                    prob = P.blend_with_market(raw, o["fair"])
                    dec = P.american_to_decimal(o["price"])
                    c = {**o, "prob": prob, "raw_prob": raw, "ev": prob * dec - 1,
                         "prob_edge": prob - o["fair"], "decimal": dec}
                    if best is None or c["ev"] > best["ev"]:
                        best = c
                best.update({
                    "market": market, "stat": stat, "label": label, "side": side,
                    "team": p["team"], "opponent": p["opponent"], "position": p["position"],
                    "projection": round(p["proj"][stat], 2),
                    "flags": _stability(p, stat, best["line"]), "_p": p,
                })
                cands.append(best)
    return cands


# ---------- plain-English reasons ----------

def _pct(x):
    return f"{x * 100:.0f}%"


def explain(c):
    p, u, ctx = c["_p"], c["_p"]["usage"], c["_p"]["ctx"]
    team = TEAM_NICK.get(c["team"], c["team"])
    opp = TEAM_NICK.get(c["opponent"], c["opponent"])
    stat, side = c["stat"], c["side"]
    bullets = []

    if stat == "tds":
        bullets.append(f"Model gives him a {_pct(c['raw_prob'])} chance to score; the odds imply "
                       f"about {_pct(c['fair'])}.")
        bullets.append(f"Gets {_pct(u['rz_share'])} of the {team}' red-zone touches.")
    else:
        unit = "catches" if stat == "receptions" else "yards"
        bullets.append(f"Model projects {c['projection']:.0f} {unit} vs. a line of {c['line']} "
                       f"({_pct(c['raw_prob'])} chance to go {side.lower()} on its own).")
        if stat == "pass_yds":
            bullets.append(f"Expected to throw about {p['proj']['pass_att']:.0f} times"
                           + (f"; completion % over expected is {u['cpoe']:+.1f} lately."
                              if u.get("cpoe") is not None else "."))
        elif stat == "rush_yds":
            bullets.append(f"Handles {_pct(u['carry_share'])} of the {team}' carries "
                           f"(about {p['proj']['carries']:.0f} expected).")
        else:
            bullets.append(f"Earns {_pct(u['target_share'])} of the {team}' targets and "
                           f"{_pct(u['air_share'])} of their air yards, on {_pct(u['snap'])} of snaps.")

    extra = []
    factor = p["factors"].get(stat)
    if factor and abs(factor - 1) >= 0.05:
        more = "more" if factor > 1 else "fewer"
        extra.append(f"The {opp} defense allows {abs(factor - 1) * 100:.0f}% {more} {c['label']} "
                     f"to {c['position']}s than average.")
    if p["teammates_out"] and stat in ("rec_yds", "receptions", "rush_yds", "tds"):
        extra.append(f"With {', '.join(p['teammates_out'][:2])} out, there's more work to go around.")
    if ctx["margin"] <= -3 and stat in ("pass_yds", "rec_yds", "receptions"):
        extra.append(f"The {team} are {abs(ctx['margin']):g}-point underdogs, so they should be throwing to catch up.")
    if ctx["margin"] >= 3 and stat == "rush_yds":
        extra.append(f"The {team} are {ctx['margin']:g}-point favorites, so expect a lot of running late.")
    if ctx["notes"]:
        extra.append("Also factored in: " + ", ".join(ctx["notes"]) + ".")
    bullets.extend(extra[:1] if len(bullets) >= 2 else extra[:2])
    return bullets[:3]


def _pick_dict(c, tier):
    side_word = {"Over": "Over", "Under": "Under", "Yes": "Yes"}[c["side"]]
    line = f" {c['line']}" if c["line"] is not None else ""
    return {
        "tier": tier, "player": c["player"], "team": c["team"], "position": c["position"],
        "market": c["market"], "label": c["label"], "side": side_word, "line": c["line"],
        "title": f"{c['player']} {side_word}{line} {c['label']}",
        "price": c["price"], "book": c["book"],
        "model_prob": round(c["prob"], 4), "fair_prob": round(c["fair"], 4),
        "prob_edge": round(c["prob_edge"], 4), "edge": round(c["ev"], 4),
        "projection": c["projection"], "flags": c["flags"], "why": explain(c),
    }


def _joint(pa, pb, rho):
    return pa * pb + rho * ((pa * (1 - pa) * pb * (1 - pb)) ** 0.5)


def _correlated(a, b):
    """Return the correlation between two legs, or 0 if we don't model it."""
    if a["team"] != b["team"] or a["player"] == b["player"]:
        return 0.0
    qb, other = (a, b) if a["stat"] == "pass_yds" else (b, a) if b["stat"] == "pass_yds" else (None, None)
    # only the QB's main targets move closely with his yardage
    if (qb and other["stat"] in ("rec_yds", "receptions") and qb["side"] == other["side"]
            and other["_p"]["usage"]["target_share"] >= 0.15):
        return ETF_RHO
    return 0.0


def select(cands):
    usable = [c for c in cands if "model is far from the market" not in c["flags"]]

    def is_under(c):
        return c["side"] == "Under"

    blue = sorted(
        (c for c in usable if not c["flags"]
         and c["prob_edge"] >= (UNDER_MIN_PROB_EDGE if is_under(c) else BLUE_MIN_PROB_EDGE)
         and BLUE_PRICE_RANGE[0] <= c["price"] <= BLUE_PRICE_RANGE[1]),
        key=lambda c: c["prob_edge"] + (0 if is_under(c) else OVER_BONUS), reverse=True)
    blue_chips, used = [], set()
    for c in blue:
        # one pick per player, and at most 2 from one team so a single bad
        # read on an offense can't sink the whole card
        if c["player"] in used or sum(b["team"] == c["team"] for b in blue_chips) >= 2:
            continue
        if is_under(c) and sum(is_under(b) for b in blue_chips) >= MAX_BLUE_UNDERS:
            continue
        blue_chips.append(c)
        used.add(c["player"])
        if len(blue_chips) == 3:
            break

    penny = sorted(
        (c for c in usable
         if PENNY_PRICE_RANGE[0] <= c["price"] <= PENNY_PRICE_RANGE[1]
         and not is_under(c)
         and c["ev"] >= PENNY_MIN_EDGE and c["prob_edge"] > 0 and c["player"] not in used
         and c["_p"]["usage"]["games"] >= 3 and "listed Questionable" not in c["flags"]),
        key=lambda c: c["ev"], reverse=True)
    penny_stocks = []
    for c in penny:
        if c["player"] in used:
            continue
        penny_stocks.append(c)
        used.add(c["player"])
        if len(penny_stocks) == 2:
            break

    legs = [c for c in usable if c["prob_edge"] > 0 and c["side"] == "Over"
            and "listed Questionable" not in c["flags"]]
    etfs = []
    for a, b in itertools.combinations(legs, 2):
        rho = _correlated(a, b)
        if not rho:
            continue
        joint = _joint(a["prob"], b["prob"], rho)
        # Books price same-game parlays knowing the legs are linked, so the
        # payout is estimated from the book's own fair odds plus its usual cut
        dec = 1 / (_joint(a["fair"], b["fair"], rho) * SGP_MARGIN)
        etfs.append({"legs": [a, b], "joint": joint, "decimal": dec, "ev": joint * dec - 1})
    etfs = sorted((e for e in etfs if e["ev"] > 0), key=lambda e: e["ev"], reverse=True)
    chosen, seen = [], set()
    for e in etfs:
        ids = {(leg["player"], leg["market"]) for leg in e["legs"]}
        if ids & seen:
            continue
        chosen.append(e)
        seen |= ids
        if len(chosen) == 2:
            break

    return {
        "blue_chips": [_pick_dict(c, "Blue Chip") for c in blue_chips],
        "penny_stocks": [_pick_dict(c, "Penny Stock") for c in penny_stocks],
        "etfs": [{
            "tier": "ETF",
            "legs": [_pick_dict(leg, "ETF leg") for leg in e["legs"]],
            "model_prob": round(e["joint"], 4),
            "price": P.decimal_to_american(e["decimal"]),
            "edge": round(e["ev"], 4),
            "why": [f"{e['legs'][0]['player']} and {e['legs'][1]['player']} are on the same "
                    "offense: " + ("when the QB has a big passing day, his top receivers usually do too."
                                   if e["legs"][0]["side"] == "Over" else
                                   "when the QB has a quiet day, his top receivers usually do too."),
                    f"Model gives both legs a {_pct(e['joint'])} chance to hit together. The price "
                    f"(about {P.decimal_to_american(e['decimal']):+d}) is our estimate of a same-game "
                    "parlay; check your book's exact number."],
        } for e in chosen],
    }
