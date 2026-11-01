"""Game-day runner: stays awake and does each job on time.

GitHub often skips or delays frequent scheduled runs, so instead of hoping a
15-minute check fires at the right moment, this runner sleeps until each job
is due and does it itself:

  kickoff - 80 min   refresh injuries/weather (and props if missing), FINAL picks
  kickoff + 3h20m    grade the game (retries every 20 min until ESPN has it final)

A GitHub job can only run for 6 hours, so before time runs out the runner starts
a fresh copy of itself if there's still work in the next day. When nothing is
left within RESTART_HORIZON, it just stops. The daily run (and the backup
15-minute check) start it again.

Usage: python scripts/gameday.py
Needs GH_TOKEN (to start the website build and its own next copy).
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
FINALIZE_BEFORE = timedelta(minutes=80)
GRADE_AFTER = timedelta(hours=3, minutes=20)
GRADE_RETRY = timedelta(minutes=20)
RUN_BUDGET = timedelta(minutes=335)      # GitHub's limit is 6 hours
# keep going if anything is due this soon (HORIZON_HOURS overrides it, for testing)
RESTART_HORIZON = timedelta(hours=float(os.environ.get("HORIZON_HOURS") or 30))


def now():
    return datetime.now(ET)


def log(msg):
    print(f"[{now():%a %H:%M} ET] {msg}", flush=True)


def sh(*cmd, check=True):
    log("$ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, check=check)


def save(message):
    """Commit data/ and push; on a clash with another run, our copy wins."""
    sh("git", "add", "data")
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
        return False
    sh("git", "commit", "-q", "-m", message)
    for attempt in range(4):
        pull = sh("git", "pull", "-q", "--rebase", "-X", "theirs", "origin", "main", check=False)
        if pull.returncode == 0 and sh("git", "push", "-q", check=False).returncode == 0:
            return True
        sh("git", "rebase", "--abort", check=False)
        time.sleep(10 * (attempt + 1))
    raise RuntimeError("could not push data")


def publish():
    sh("gh", "workflow", "run", "pages.yml", "--ref", "main", check=False)


def games():
    import csv
    with open(ROOT / "data" / "stats" / "games.csv") as f:
        for g in csv.DictReader(f):
            g["kickoff"] = datetime.fromisoformat(f"{g['gameday']}T{g['gametime']}").replace(tzinfo=ET)
            yield g


def card(game_id):
    path = ROOT / "data" / "picks" / f"{game_id}.json"
    return json.loads(path.read_text()) if path.exists() else None


def graded_ids():
    path = ROOT / "data" / "portfolio" / "ledger.json"
    return {r["game_id"] for r in json.loads(path.read_text())} if path.exists() else set()


def plan(retry_after):
    """(due finalize ids, due grade ids, next future event time or None)."""
    t, done = now(), graded_ids()
    fin, grade, upcoming = [], [], []
    for g in games():
        c = card(g["game_id"])
        if g["kickoff"] > t and (c is None or c["status"] != "FINAL"):
            when = max(g["kickoff"] - FINALIZE_BEFORE, retry_after.get("final " + g["game_id"], t))
            (fin.append(g["game_id"]) if when <= t else upcoming.append(when))
        has_picks = c and (c["blue_chips"] or c["penny_stocks"] or c["etfs"])
        if has_picks and g["game_id"] not in done and t - g["kickoff"] < timedelta(days=2):
            when = max(g["kickoff"] + GRADE_AFTER, retry_after.get(g["game_id"], t))
            (grade.append(g["game_id"]) if when <= t else upcoming.append(when))
    return fin, grade, min(upcoming, default=None)


def main():
    start = now()
    retry_after = {}
    while True:
        sh("git", "pull", "-q", "--rebase", "-X", "theirs", "origin", "main", check=False)
        fin, grade, nxt = plan(retry_after)
        if fin:
            log(f"finalizing {' '.join(fin)}")
            sh("python", "scripts/update_data.py", "--games", *fin, check=False)
            sh("python", "scripts/run_model.py", "--final", *fin, check=False)
            for gid in fin:
                c = card(gid)
                if c is None or c["status"] != "FINAL":  # something failed: try again shortly
                    retry_after["final " + gid] = now() + timedelta(minutes=10)
            if save(f"FINAL picks: {' '.join(fin)}"):
                publish()
            continue
        if grade:
            log(f"grading {' '.join(grade)}")
            sh("python", "scripts/grade.py", check=False)
            still = set(grade) - graded_ids()
            for gid in still:  # not final on ESPN/nflverse yet
                retry_after[gid] = now() + GRADE_RETRY
            if save("Graded picks: " + " ".join(sorted(set(grade) - still))):
                publish()
            continue

        if nxt is None or nxt - now() > RESTART_HORIZON:
            log("nothing due in the next day, stopping")
            return
        left = start + RUN_BUDGET - now()
        if nxt - now() > left:
            if left > timedelta(minutes=5):
                # use up this run's time first; otherwise each fresh copy would
                # see the same far-off job and restart straight away, forever
                log(f"next job at {nxt:%a %H:%M} ET; waiting out this run's time limit first")
                time.sleep((left - timedelta(minutes=2)).total_seconds())
                continue
            log(f"next job at {nxt:%a %H:%M} ET is past this run's time limit, starting a fresh runner")
            sh("gh", "workflow", "run", "gameday.yml", "--ref", "main", check=False)
            return
        wait = max((nxt - now()).total_seconds(), 30)
        log(f"sleeping until {nxt:%a %H:%M} ET")
        time.sleep(wait)


if __name__ == "__main__":
    sys.exit(main())
