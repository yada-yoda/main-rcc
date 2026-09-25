"""Feed health check for the Stage Wire ingest.

    python check_feeds.py            every enabled source
    python check_feeds.py --all      disabled ones too

Fetches each source in feeds.json and reports HTTP status, item count and how
old the newest item is. Feeds rot quietly - an outlet redesigns, a section
moves, a CDN starts refusing non-browser clients - and the ingest just stops
seeing that outlet without complaining. Run this before trusting a thin run,
and after editing feeds.json.

Exits non-zero if any enabled source failed, so the Action can surface it.
Writes nothing.
"""

import json
import sys
import time
from pathlib import Path
from urllib.parse import quote

import wire

ROOT = Path(__file__).resolve().parent
FEEDS = ROOT / "feeds.json"

STALE_DAYS = 30


def describe_age(hours):
    if hours is None:
        return "no dates"
    if hours < 1:
        # Can go slightly negative: BroadwayWorld labels its timestamps EST
        # year-round, so in summer everything it publishes looks an hour ahead.
        return "just now"
    if hours < 48:
        return f"{hours:.0f}h old"
    return f"{hours / 24:.0f}d old"


def check(label, url, timeout):
    try:
        items = wire.parse_feed(wire.fetch(url, timeout=timeout))
    except Exception as e:
        msg = str(e).replace("\n", " ")
        print(f"  {'FAIL':6} {label:24} {msg[:60]}")
        return False

    dated = [i.published for i in items if i.published]
    newest = max(dated) if dated else None
    hours = wire.age_hours(newest)

    if not items:
        verdict = "EMPTY"
    elif not dated:
        verdict = "NODATE"
    elif hours > STALE_DAYS * 24:
        verdict = "STALE"
    else:
        verdict = "ok"

    undated = len(items) - len(dated)
    extra = f"  ({undated} undated)" if undated and dated else ""
    print(f"  {verdict:6} {label:24} {len(items):3} items  {describe_age(hours)}{extra}")
    return verdict == "ok"


def main():
    show_all = "--all" in sys.argv
    cfg = json.loads(FEEDS.read_text(encoding="utf-8"))
    caps = cfg.get("caps", {})
    timeout = caps.get("requestTimeoutSeconds", 30)
    delay = caps.get("politeDelaySeconds", 1)

    ok = bad = 0

    print("\nGoogle News queries")
    base = cfg["googleNews"]["base"]
    for q in cfg["googleNews"]["queries"]:
        if not q.get("enabled", True) and not show_all:
            continue
        if check(q["id"], base.replace("{q}", quote(q["q"])), timeout):
            ok += 1
        else:
            bad += 1
        time.sleep(delay)

    print("\nDirect feeds")
    for f in cfg["feeds"]:
        if not f.get("enabled", True) and not show_all:
            continue
        if check(f["id"], f["url"], timeout):
            ok += 1
        else:
            bad += 1
        time.sleep(delay)

    retired = cfg.get("retired", [])
    if retired:
        print("\nRetired (not fetched): " + ", ".join(r["name"] for r in retired))

    print(f"\n{ok} working, {bad} not.\n")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
