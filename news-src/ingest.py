"""Stage Wire ingest: read the feeds, file the stories, write the data file.

    python ingest.py --dry-run              fetch and classify, write nothing
    python ingest.py --dry-run --no-people  same, but skip Wikidata (fast)
    python ingest.py                        the real thing, writes data/
    python ingest.py --source playbill      one source, for debugging

Run by .github/workflows/news-ingest.yml four times a day. Writes only
data/stories.json and data/wikidata-cache.json, and the workflow commits only
when those actually change, so a quiet news day leaves no commit behind.

Design notes worth knowing before changing anything:

  * Nothing is invented. A story's summary is the feed's own description,
    trimmed, stored as a quote with the outlet named. Article body text is
    never copied.
  * A story the rules are unsure about gets status "review" and stays off the
    page. Being wrong in public on a domain that also carries an acting
    resume is worse than being thin.
  * overrides.json is applied last and always wins, so a bad call can be
    fixed in one line without touching code.
  * Timestamps are recorded once, as firstSeen. Nothing in the output changes
    on a run where the news did not, which is what keeps the commit history
    quiet.
"""

import argparse
import base64
import datetime as dt
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse, parse_qsl, urlencode

import classify
import people as people_mod
import wire

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
STORIES = DATA / "stories.json"
CACHE = DATA / "wikidata-cache.json"

VERSION = "0.1.0"

# Query parameters that identify a campaign rather than a page.
TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_", "igshid", "ref_")
TRACKING_EXACT = {"ref", "source", "cmpid", "sr_share", "oc"}

CLUSTER_DAYS = 14


# ---------------------------------------------------------------- utilities


def log(*a):
    print(*a, file=sys.stderr)


def strip_tracking(url):
    """Drop campaign parameters so the same article from two feeds dedupes."""
    try:
        p = urlparse(url)
    except ValueError:
        return url
    keep = [
        (k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
        if not (k.lower().startswith(TRACKING_PREFIXES) or k.lower() in TRACKING_EXACT)
    ]
    return urlunparse(p._replace(query=urlencode(keep), fragment=""))


GNEWS_URL_RE = re.compile(rb"https?://[\w\-./%?=&+#:~]{12,}")


def unwrap_google(url):
    """Google News links point at news.google.com and carry the real URL in a
    base64 segment. Decoding it avoids sending readers through a redirect and
    lets the same article dedupe against a direct feed's copy.

    Newer links are not decodable this way. Those keep the Google URL, which
    still works for a human clicking it - the cost is only a missed dedupe.
    """
    if "news.google.com" not in url:
        return url
    m = re.search(r"/(?:rss/)?articles/([A-Za-z0-9_\-]+)", url)
    if not m:
        return url
    seg = m.group(1)
    try:
        raw = base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))
    except Exception:
        return url
    found = GNEWS_URL_RE.search(raw)
    if not found:
        return url
    try:
        candidate = found.group(0).decode("utf-8")
    except UnicodeDecodeError:
        return url
    if "google.com" in candidate:
        return url
    return candidate


GNEWS_TITLE_SUFFIX = re.compile(r"\s+-\s+([^-]{2,40})$")


def split_source_from_title(title):
    """Google News appends ' - Publisher' to every headline."""
    m = GNEWS_TITLE_SUFFIX.search(title or "")
    if not m:
        return title, ""
    return title[: m.start()].strip(), m.group(1).strip()


def norm_title(title):
    t = re.sub(r"[^a-z0-9 ]+", " ", (title or "").lower())
    return re.sub(r"\s+", " ", t).strip()


def two_sentences(text, limit=320):
    """The feed's own description, trimmed to two sentences. Never our words,
    never the article body."""
    text = wire.strip_tags(text or "").strip()
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = " ".join(parts[:2]).strip()
    if len(out) > limit:
        out = out[: limit - 1].rstrip() + "…"
    return out


def story_id(key):
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def is_echo(quote, title):
    """Google News descriptions are the headline wrapped in a link plus the
    outlet name. Stripped of tags that reads 'Gina Torres to Star in Buena
    Vista Social Club on Broadway imdb.com', which is not a summary of
    anything. Better no quote than the headline said twice."""
    q, t = norm_title(quote), norm_title(title)
    if not q or not t:
        return False
    return t in q or q in t


# Outlet names arrive as a mix of brand names and bare domains, sometimes both
# for the same outlet in one story. This keeps the source line readable.
SOURCE_FIXES = {
    "deadline.com": "Deadline",
    "variety.com": "Variety",
    "playbill.com": "Playbill",
    "broadwayworld.com": "BroadwayWorld",
    "nytimes.com": "The New York Times",
    "hollywoodreporter.com": "The Hollywood Reporter",
    "theatermania.com": "TheaterMania",
    "whatsonstage.com": "WhatsOnStage",
    "ticketnews.com": "TicketNews",
    "broadwaynews.com": "Broadway News",
    "nystagereview.com": "New York Stage Review",
    "americantheatre.org": "American Theatre",
    "newcitystage.com": "Newcity Stage",
    "chicagoonstage.com": "Chicago Onstage",
    "chicagoreader.com": "Chicago Reader",
    "chicagotribune.com": "Chicago Tribune",
    "imdb.com": "IMDb",
}


def tidy_source(name):
    if not name:
        return ""
    key = name.strip().lower().removeprefix("www.")
    if key in SOURCE_FIXES:
        return SOURCE_FIXES[key]
    # A bare domain nobody has mapped yet reads better without its suffix.
    if "." in key and " " not in key:
        stem = key.split(".")[0]
        return stem[:1].upper() + stem[1:]
    return name.strip()


# ---------------------------------------------------------------- collecting


def collect(cfg, only=None, timeout=30, delay=1.0):
    """Fetch every enabled source and return raw items tagged with their feed."""
    items = []
    failures = []

    base = cfg["googleNews"]["base"]
    for q in cfg["googleNews"]["queries"]:
        if not q.get("enabled", True) or (only and q["id"] not in only):
            continue
        url = base.replace("{q}", quote(q["q"]))
        try:
            got = wire.parse_feed(wire.fetch(url, timeout=timeout))
            for it in got:
                it.feed_id = q["id"]
                it.feed_name = ""     # Google News names the outlet per item
            items += got
            log(f"  {q['id']:24} {len(got):3} items")
        except Exception as e:
            failures.append((q["id"], str(e)[:80]))
            log(f"  {q['id']:24} FAILED {str(e)[:60]}")
        time.sleep(delay)

    for f in cfg["feeds"]:
        if not f.get("enabled", True) or (only and f["id"] not in only):
            continue
        try:
            got = wire.parse_feed(wire.fetch(f["url"], timeout=timeout))
            wanted = [w.lower() for w in (f.get("categoryContains") or [])]
            if wanted:
                before = len(got)
                got = [
                    it for it in got
                    if any(w in (cat or "").lower() for cat in it.categories for w in wanted)
                ]
                log(f"  {f['id']:24} {len(got):3} items  (category filter kept {len(got)}/{before})")
            else:
                log(f"  {f['id']:24} {len(got):3} items")
            for it in got:
                it.feed_id = f["id"]
                it.feed_name = f["name"]
            items += got
        except Exception as e:
            failures.append((f["id"], str(e)[:80]))
            log(f"  {f['id']:24} FAILED {str(e)[:60]}")
        time.sleep(delay)

    return items, failures


# ---------------------------------------------------------------- filing


def file_story(item, venues, max_age_days, now):
    """Turn one feed item into a filed story, or return (None, reason)."""
    title, gnews_source = split_source_from_title(item.title)
    if not title:
        return None, "no title"

    text = classify.haystack(title, item.summary)

    discarded = classify.should_discard(text)
    if discarded:
        return None, f"discard:{discarded}"

    published = wire.clamp_future(item.published, now)
    if published is None:
        return None, "undated"
    if (now - published).days > max_age_days:
        return None, "too old"

    city, tier, venue, how = classify.classify_place(text, venues, title.lower())
    kind, phrase = classify.classify_type(text)

    # Neither a place nor a type means this is not a theatre story at all -
    # a Google News query catching the wrong Paramount, say. The review
    # bucket is for stories that are plainly ours but ambiguous in one
    # dimension; off-topic noise does not belong in it.
    if city is None and kind is None:
        return None, "off topic"

    outlet = tidy_source(item.source or gnews_source or item.feed_name or item.feed_id)
    link = strip_tracking(unwrap_google(item.link))

    quote = two_sentences(item.summary)
    if is_echo(quote, title):
        quote = ""

    return {
        "title": title,
        "city": city,
        "tier": tier,
        "venue": venue,
        "placedBy": how,
        "type": kind,
        "typePhrase": phrase,
        "show": classify.show_title(title),
        "quote": quote,
        "quoteSource": outlet,
        "published": published,
        "source": {"name": outlet, "url": link, "feed": item.feed_id},
        "names": classify.extract_names(title),
    }, None


def cluster_key(s):
    """Same show plus same lead name is the same story, however many outlets
    wrote it up. Falling back to the normalized headline still catches the
    common case of two feeds carrying identical wire copy.

    Show titles are normalized hard before comparison. One outlet writes
    WE'LL SEE and another writes 'We'll See', and unnormalized those are two
    different stories on the page.
    """
    show = norm_title(s.get("show") or "")
    lead = norm_title(s["names"][0]) if s.get("names") else ""
    if show and lead:
        return f"{show}|{lead}"
    if show:
        return f"show|{show}"
    if lead and s.get("type"):
        return f"{lead}|{s['type']}|{s.get('city') or '?'}"
    return "t|" + norm_title(s["title"])


# ---------------------------------------------------------------- main


def build(args):
    now = dt.datetime.now(dt.timezone.utc)
    cfg = json.loads((ROOT / "feeds.json").read_text(encoding="utf-8"))
    venues = classify.load_venues()
    overrides = json.loads((ROOT / "overrides.json").read_text(encoding="utf-8"))
    caps = cfg.get("caps", {})

    only = set(args.source.split(",")) if args.source else None

    log("Fetching")
    items, failures = collect(
        cfg, only,
        timeout=caps.get("requestTimeoutSeconds", 30),
        delay=0 if args.fast else caps.get("politeDelaySeconds", 1),
    )
    log(f"  {len(items)} items from {len(cfg['googleNews']['queries']) + len(cfg['feeds'])} sources")

    # --- file each item -------------------------------------------------
    filed, reasons = [], {}
    for it in items:
        s, why = file_story(it, venues, caps.get("maxAgeDays", 21), now)
        if s is None:
            reasons[why.split(":")[0]] = reasons.get(why.split(":")[0], 0) + 1
            continue
        filed.append(s)

    log("\nFiled")
    log(f"  kept {len(filed)}, dropped {sum(reasons.values())}")
    for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]):
        log(f"    {k:14} {v}")

    # --- cluster --------------------------------------------------------
    clusters = {}
    for s in filed:
        key = cluster_key(s)
        c = clusters.get(key)
        if c is None:
            clusters[key] = c = {
                "key": key,
                "title": s["title"],
                "city": s["city"],
                "tier": s["tier"],
                "venue": s["venue"],
                "placedBy": s["placedBy"],
                "type": s["type"],
                "show": s["show"],
                "quote": s["quote"],
                "quoteSource": s["quoteSource"],
                "published": s["published"],
                "sources": [],
                "names": [],
            }
        # earliest timestamp wins; a later outlet does not make it newer
        if s["published"] < c["published"]:
            c["published"] = s["published"]
        # fill in anything the first copy of the story lacked
        for field in ("city", "tier", "venue", "type", "show"):
            if not c.get(field) and s.get(field):
                c[field] = s[field]
        if not c["quote"] and s["quote"]:
            c["quote"], c["quoteSource"] = s["quote"], s["quoteSource"]
        if not any(x["url"] == s["source"]["url"] for x in c["sources"]):
            c["sources"].append(s["source"])
        for n in s["names"]:
            if n not in c["names"]:
                c["names"].append(n)

    log(f"\nClustered to {len(clusters)} stories")

    def absorb(into, other):
        """Fold one cluster into another, keeping the better of each field.

        The absorbed cluster's id is remembered, because the previous run
        wrote it to stories.json as a story of its own and the carry-forward
        below would otherwise resurrect the duplicate we just merged away.
        """
        into.setdefault("absorbed", []).append(story_id(other["key"]))
        into["absorbed"] += other.get("absorbed", [])
        if other["published"] < into["published"]:
            into["published"] = other["published"]
        for field in ("city", "tier", "venue", "type", "show"):
            if not into.get(field) and other.get(field):
                into[field] = other[field]
        # Prefer a real summary over none, and the fuller of two summaries.
        if len(other.get("quote") or "") > len(into.get("quote") or ""):
            into["quote"], into["quoteSource"] = other["quote"], other["quoteSource"]
        for s in other["sources"]:
            if not any(x["url"] == s["url"] for x in into["sources"]):
                into["sources"].append(s)
        for n in other["names"]:
            if n not in into["names"]:
                into["names"].append(n)

    # --- people ---------------------------------------------------------
    cache_days_note = ""
    ppl = people_mod.People(
        CACHE,
        min_score=args.min_score,
        delay=0 if args.fast else 1.0,
        enabled=not args.no_people,
    )
    for c in clusters.values():
        c["celebs"] = ppl.celebrities(c["names"][:6]) if c["names"] else []
    if not args.no_people:
        cache_days_note = f", {ppl.lookups} Wikidata lookups"

    # --- second clustering pass, now that the names are known ------------
    # The first pass keys on the show title, which only some headlines carry:
    # "'Evita' On Broadway: Rachel Zegler To Be Joined By..." and "Casting
    # announced for Evita with Rachel Zegler" are one story that stayed two,
    # because only the first quoted the title. A shared celebrity, the same
    # kind of news, the same city and a fortnight's window is the same story.
    by_person = {}
    merged = 0
    for c in sorted(clusters.values(), key=lambda x: x["published"]):
        if c.get("_gone"):
            continue
        for celeb in c["celebs"]:
            key = (celeb["name"].lower(), c["type"], c["city"])
            if not all(key):
                continue
            first = by_person.get(key)
            if first is None:
                by_person[key] = c
                continue
            if abs((c["published"] - first["published"]).days) <= CLUSTER_DAYS:
                absorb(first, c)
                c["_gone"] = True
                merged += 1
                break

    if merged:
        for key in [k for k, c in clusters.items() if c.get("_gone")]:
            del clusters[key]
        log(f"  merged {merged} duplicate(s) on shared name + type + city")

    # --- assemble -------------------------------------------------------
    existing = {}
    if STORIES.exists():
        try:
            prev = json.loads(STORIES.read_text(encoding="utf-8"))
            existing = {s["id"]: s for s in prev.get("stories", [])}
        except (json.JSONDecodeError, KeyError):
            log("  previous stories.json unreadable, starting fresh")

    out = []
    for c in clusters.values():
        sid = story_id(c["key"])
        was = existing.get(sid)
        status = "published" if (c["city"] and c["type"]) else "review"
        story = {
            "id": sid,
            "firstSeen": was["firstSeen"] if was else c["published"].isoformat(timespec="seconds"),
            "published": c["published"].isoformat(timespec="seconds"),
            "city": c["city"],
            "tier": c["tier"],
            "venue": c["venue"],
            "placedBy": c["placedBy"],
            "type": c["type"],
            "show": c["show"],
            "title": c["title"],
            "quote": c["quote"],
            "quoteSource": c["quoteSource"],
            "celebs": c["celebs"],
            "sources": c["sources"],
            "status": status,
        }
        out.append(story)

    # keep stories that have aged out of the feeds but are still in range
    cutoff = now - dt.timedelta(days=caps.get("maxAgeDays", 21))
    seen_ids = {s["id"] for s in out}
    absorbed_ids = {i for c in clusters.values() for i in c.get("absorbed", [])}
    for sid, old in existing.items():
        if sid in seen_ids or sid in absorbed_ids:
            continue
        try:
            when = dt.datetime.fromisoformat(old["published"])
        except (KeyError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.timezone.utc)
        if when >= cutoff:
            out.append(old)

    # --- overrides, applied last and always winning ----------------------
    hidden = 0
    for s in out:
        o = overrides.get(s["id"])
        if not o:
            continue
        if o.get("hide"):
            s["status"] = "hidden"
            hidden += 1
            continue
        for k, v in o.items():
            if k != "hide":
                s[k] = v
        if s.get("city") and s.get("type") and s["status"] == "review":
            s["status"] = "published"

    out.sort(key=lambda s: s["published"], reverse=True)

    counts = {
        "total": len(out),
        "published": sum(1 for s in out if s["status"] == "published"),
        "review": sum(1 for s in out if s["status"] == "review"),
        "hidden": hidden,
        "newYork": sum(1 for s in out if s.get("city") == "New York"),
        "chicago": sum(1 for s in out if s.get("city") == "Chicago"),
        "withCelebs": sum(1 for s in out if s.get("celebs")),
    }

    log("\nResult")
    for k, v in counts.items():
        log(f"  {k:12} {v}")
    if failures:
        log(f"\n  {len(failures)} source(s) failed: " + ", ".join(f[0] for f in failures))
    log(f"\n{len(out)} stories{cache_days_note}")

    return {"version": VERSION, "stories": out}, counts, ppl


def main():
    p = argparse.ArgumentParser(description="Stage Wire news ingest")
    p.add_argument("--dry-run", action="store_true", help="classify but write nothing")
    p.add_argument("--no-people", action="store_true", help="skip Wikidata lookups")
    p.add_argument("--fast", action="store_true", help="no polite delays (local only)")
    p.add_argument("--source", help="comma separated source ids to fetch")
    p.add_argument("--min-score", type=int, default=25, help="fame threshold")
    p.add_argument("--show", type=int, default=0, help="print N filed stories")
    args = p.parse_args()

    payload, counts, ppl = build(args)

    if args.show:
        for s in payload["stories"][: args.show]:
            celebs = ", ".join(c["name"] for c in s["celebs"]) or "-"
            print(f"\n[{s['status']}] {s.get('city') or '?'} / {s.get('tier') or '?'} / {s.get('type') or '?'}")
            print(f"  {s['title']}")
            print(f"  venue: {s.get('venue') or '-'}  ({s['placedBy']})  celebs: {celebs}")
            print(f"  {len(s['sources'])} source(s), first: {s['sources'][0]['name'] if s['sources'] else '-'}")

    # The Wikidata cache is saved even on a dry run. It is only a cache, and
    # throwing away lookups already paid for just means asking again.
    DATA.mkdir(parents=True, exist_ok=True)
    if args.dry_run:
        if ppl.save():
            log(f"\nWrote {CACHE.relative_to(ROOT)} (cache only)")
        log("Dry run: stories.json not written.")
        return 0

    text = json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=False) + "\n"
    before = STORIES.read_text(encoding="utf-8") if STORIES.exists() else ""
    if text == before:
        log("\nNo change to stories.json.")
    else:
        STORIES.write_text(text, encoding="utf-8")
        log(f"\nWrote {STORIES.relative_to(ROOT)}")
    if ppl.save():
        log(f"Wrote {CACHE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
