"""Where everything is saved, plus small save/load helpers."""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STATS = DATA / "stats"
ODDS = DATA / "odds"
PROPS = ODDS / "props"

ET = ZoneInfo("America/New_York")


def now_et():
    return datetime.now(ET)


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=str) + "\n")


def load_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def save_csv(path, df):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_csv(path)
