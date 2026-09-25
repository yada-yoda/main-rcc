"""Who is in this story, and would anyone outside the theatre have heard of them.

Wikidata answers both, for free and without an account. For each candidate
name pulled out of a headline:

  * is this a human (P31 = Q5) whose occupation (P106) is performing - actor,
    stage/film/TV actor, singer, musician, comedian
  * how widely known are they, approximated by how many language editions of
    Wikipedia have an article about them (sitelink count)
  * what are they known for (P800 notable works, falling back to the short
    description)

The sitelink count is a crude fame proxy and is meant to be. It is public,
free, stable, and hard to game, and the alternative - a paid entity API or an
LLM guess - fails the "free and runs itself" requirement this whole section
is built on. The threshold is tunable and should be tuned on real data.

Every name is looked up once, ever, and cached to disk. A miss is cached too:
without that, common false positives out of the name extractor would be
re-queried on every run forever.
"""

import datetime as dt
import json
import re
import time
import urllib.parse
from pathlib import Path

import wire

API = "https://www.wikidata.org/w/api.php"

HUMAN = "Q5"

# Occupations that count as a performer for our purposes.
PERFORMER_QIDS = {
    "Q33999",    # actor
    "Q10800557", # film actor
    "Q10798782", # television actor
    "Q2259451",  # stage actor
    "Q177220",   # singer
    "Q639669",   # musician
    "Q245068",   # comedian
    "Q2405480",  # voice actor
    "Q947873",   # television presenter
}

# Re-check a cached name after this long: someone's fame moves, and a person
# who had no Wikidata entry last year may have one now.
CACHE_DAYS = 90


def _get(params, timeout=30):
    url = API + "?" + urllib.parse.urlencode(params)
    return json.loads(wire.fetch(url, timeout=timeout).decode("utf-8"))


class People:
    def __init__(self, cache_path, min_score=25, delay=1.0, enabled=True):
        self.cache_path = Path(cache_path)
        self.min_score = min_score
        self.delay = delay
        self.enabled = enabled
        self.cache = {}
        self.dirty = False
        self.lookups = 0
        if self.cache_path.exists():
            try:
                self.cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                # A truncated cache is a cache, not a crash. Start clean.
                self.cache = {}

    # ---- cache ---------------------------------------------------------

    def _fresh(self, entry):
        try:
            checked = dt.datetime.fromisoformat(entry["checkedAt"])
        except (KeyError, ValueError):
            return False
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=dt.timezone.utc)
        return (dt.datetime.now(dt.timezone.utc) - checked).days < CACHE_DAYS

    def save(self):
        if not self.dirty:
            return False
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self.cache, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return True

    # ---- lookups -------------------------------------------------------

    def _search(self, name):
        data = _get({
            "action": "wbsearchentities",
            "search": name,
            "language": "en",
            "uselang": "en",
            "type": "item",
            "limit": 3,
            "format": "json",
        })
        return [hit["id"] for hit in data.get("search", [])]

    def _entities(self, ids, props="claims|sitelinks|descriptions|labels"):
        if not ids:
            return {}
        data = _get({
            "action": "wbgetentities",
            "ids": "|".join(ids),
            "props": props,
            "languages": "en",
            "format": "json",
        })
        return data.get("entities", {})

    @staticmethod
    def _claim_ids(entity, prop):
        out = []
        for c in entity.get("claims", {}).get(prop, []):
            try:
                out.append(c["mainsnak"]["datavalue"]["value"]["id"])
            except (KeyError, TypeError):
                continue
        return out

    def _labels(self, ids):
        if not ids:
            return {}
        ents = self._entities(ids, props="labels")
        return {
            qid: e.get("labels", {}).get("en", {}).get("value")
            for qid, e in ents.items()
        }

    def look_up(self, name):
        """Return a cache entry dict for a name. Never raises: a Wikidata
        outage should thin the celebrity chips, not fail the whole run."""
        cached = self.cache.get(name)
        if cached and self._fresh(cached):
            return cached

        entry = {
            "qid": None,
            "isPerson": False,
            "isPerformer": False,
            "score": 0,
            "knownFor": [],
            "description": None,
            "checkedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        }

        if not self.enabled:
            return entry

        try:
            self.lookups += 1
            time.sleep(self.delay)
            ids = self._search(name)
            ents = self._entities(ids[:3])

            for qid in ids[:3]:
                e = ents.get(qid)
                if not e:
                    continue
                if HUMAN not in self._claim_ids(e, "P31"):
                    continue

                occupations = set(self._claim_ids(e, "P106"))
                entry["qid"] = qid
                entry["isPerson"] = True
                entry["isPerformer"] = bool(occupations & PERFORMER_QIDS)
                entry["score"] = len(e.get("sitelinks", {}))
                entry["description"] = (
                    e.get("descriptions", {}).get("en", {}).get("value")
                )

                works = self._claim_ids(e, "P800")[:2]
                if works:
                    time.sleep(self.delay)
                    labels = self._labels(works)
                    entry["knownFor"] = [labels[w] for w in works if labels.get(w)]
                break
        except Exception as e:  # network, JSON, schema drift - all non-fatal
            entry["error"] = str(e)[:120]

        self.cache[name] = entry
        self.dirty = True
        return entry

    @staticmethod
    def _tidy_known_for(text):
        """Wikidata descriptions carry a birth year - "American actress (born
        1948)" - which is fine in a database and wrong on a chip next to a
        headline. The occupation is the useful half."""
        return re.sub(r"\s*\((?:born|b\.)[^)]*\)\s*$", "", text or "").strip()

    def celebrities(self, names):
        """Filter candidate names down to performers famous enough to show."""
        out = []
        for name in names:
            e = self.look_up(name)
            if not (e.get("isPerson") and e.get("isPerformer")):
                continue
            if e.get("score", 0) < self.min_score:
                continue
            known = e.get("knownFor") or []
            out.append({
                "name": name,
                "knownFor": ", ".join(known) if known
                            else self._tidy_known_for(e.get("description")),
                "score": e.get("score", 0),
                "qid": e.get("qid"),
            })
        out.sort(key=lambda c: -c["score"])
        return out
