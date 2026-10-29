"""Print one game's picks in plain text.

Usage: python scripts/show_picks.py [game_id]
With no game_id, shows the next game that has picks.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from propex.paths import DATA, load_json  # noqa: E402


BOOKS = {"draftkings": "DraftKings", "fanduel": "FanDuel"}


def money(price):
    return f"{price:+d}"


def pick_lines(p):
    out = [f"  {p['title']}  ({money(p['price'])} at {BOOKS.get(p['book'], p['book'])})",
           f"    Edge {p['edge'] * 100:+.1f}%  |  model {p['model_prob'] * 100:.0f}% vs. "
           f"book {p['fair_prob'] * 100:.0f}%"]
    out += [f"    - {w}" for w in p["why"]]
    return out


def main():
    files = sorted((DATA / "picks").glob("*.json"))
    if len(sys.argv) > 1:
        files = [DATA / "picks" / f"{sys.argv[1]}.json"]
    card = next((load_json(f) for f in files if load_json(f)["has_props"]), None)
    if card is None:
        print("No game has prop lines yet.")
        return
    out = [f"THE PROP EXCHANGE: {card['away']} @ {card['home']}  [{card['status']}]",
           f"Kickoff {card['weekday']} {card['kickoff'].replace('T', ' ')} ET, {card['stadium']}"]
    for team, t in card["teams"].items():
        out.append(f"  {team}: projected {t['implied_pts']} pts, {t['plays']:.0f} plays, "
                   f"{t['pass_att']:.0f} pass attempts" + (f" ({', '.join(t['notes'])})" if t["notes"] else ""))
    out.append("")
    out.append("BLUE CHIPS (strongest picks)")
    for p in card["blue_chips"] or []:
        out += pick_lines(p)
    if not card["blue_chips"]:
        out.append("  None cleared the bar today.")
    out.append("")
    out.append("PENNY STOCKS (plus-money upside)")
    for p in card["penny_stocks"]:
        out += pick_lines(p)
    if not card["penny_stocks"]:
        out.append("  None cleared the bar today.")
    out.append("")
    out.append("ETFs (two-pick bundles that tend to hit together)")
    for e in card["etfs"]:
        out.append("  " + " + ".join(leg["title"] for leg in e["legs"])
                   + f"  (about {money(e['price'])})")
        out.append(f"    Edge {e['edge'] * 100:+.1f}%  |  model {e['model_prob'] * 100:.0f}% to hit")
        out += [f"    - {w}" for w in e["why"]]
    if not card["etfs"]:
        out.append("  None cleared the bar today.")
    print("\n".join(out))


if __name__ == "__main__":
    main()
