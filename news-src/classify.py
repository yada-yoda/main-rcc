"""Turning a headline into a filed story: city, tier and type.

This is the rules half of the ingest, kept separate so it can be read and
argued with on its own. Nothing here touches the network.

The order of confidence matters and is deliberate:

  1. A venue named in the text is the hardest fact available. The Gershwin
     is on Broadway and the Goodman is in Chicago, and no phrasing changes
     that.
  2. Failing a venue, the bare words "Broadway" and "Off-Broadway" mean New
     York - unless a Chicago venue or "Broadway In Chicago" is present,
     which is exactly the trap this ordering exists to avoid.
  3. Failing both, the story has no city and goes to the review bucket
     rather than onto the page with a guess attached.

Type works the same way: an explicit closing or transfer phrase beats a
vague "announces". Reviews, interviews and photo galleries are discarded
outright - they are not news about who got cast, and they are most of what
these feeds carry by volume.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Story types, in the order they are tested. First match wins, so the more
# specific and more newsworthy phrasings come first: a headline saying a show
# "extends" is an extension even though it probably also says "announces".
TYPE_RULES = [
    ("casting", [
        "to star", "will star", "stars in", "joins the cast", "join the cast",
        "joins broadway", "will lead", "to lead", "cast set", "casting announced",
        "cast announced", "announces cast", "full cast", "casting",
        "makes broadway debut",
        "broadway debut", "will play", "to play", "takes over", "replaces",
        "steps into", "has joined", "set to star", "tapped to",
    ]),
    ("transfer", [
        "transfers", "transfer to", "moves to broadway", "move to broadway",
        "transferring", "broadway transfer", "heads to broadway", "headed to broadway",
        "eyes broadway", "broadway-bound", "broadway bound",
    ]),
    ("extension", [
        "extends", "extension", "extended run", "adds performances",
        "extends run", "extends through",
    ]),
    ("closing", [
        "sets closing", "to close", "will close", "closing date",
        "final performance", "plays final", "shutter", "ends run",
    ]),
    ("opening", [
        "opens", "opening night", "begins performances", "begin performances",
        "previews begin", "begins previews", "starts previews", "now in previews",
        "world premiere", "us premiere", "opens tonight",
    ]),
    ("new production", [
        "announces", "announced", "to produce", "new musical", "new play",
        "will premiere", "sets dates", "season announced", "announces season",
        "revival", "is coming to", "comes to broadway", "heads to the stage",
    ]),
]

# Thrown away before anything else runs. These are the bulk of the feed volume
# and none of it is news about who is doing what next.
DISCARD_PHRASES = [
    "review:", "review -", "theater review", "theatre review", "critic",
    "interview:", "interview -", "in conversation", "q&a", "q & a",
    "opinion", "essay", "column", "commentary",
    "photos:", "photo flash", "first look", "watch:", "video:", "listen:",
    "exclusive video", "recap", "best of", "roundup", "ranked", "gift guide",
    "obituary", "dies at", "has died", "remembering",
    "ticket giveaway", "sweepstakes", "deal alert", "discount",
    "what to see", "things to do", "weekend picks",
    "fall preview", "spring preview", "summer preview", "season preview",
    "tv series", "in development", "box office report",
    "box set", "cast album", "cast recording", "christmas album", "out now",
]


def load_venues(path=None):
    return json.loads((path or (ROOT / "venues.json")).read_text(encoding="utf-8"))


def haystack(item_title, item_summary):
    """The text the rules read. Lowercased once, here, so every rule below can
    assume lowercase and nothing has to remember to fold case."""
    return (str(item_title or "") + " " + str(item_summary or "")).lower()


def should_discard(text):
    """True for reviews, interviews, galleries and listicles."""
    for phrase in DISCARD_PHRASES:
        if phrase in text:
            return phrase
    return None


def match_venue(text, venues):
    """First venue whose match strings appear and whose requires/excludes are
    satisfied. Returns the venue dict, or None."""
    for v in venues:
        excludes = v.get("excludes") or []
        if any(x in text for x in excludes):
            continue
        if not any(m in text for m in v["match"]):
            continue
        requires = v.get("requires") or []
        if requires and not any(r in text for r in requires):
            continue
        return v
    return None


def match_fallback(text, fallbacks):
    for rule in fallbacks:
        if any(m in text for m in rule["match"]):
            return rule
    return None


def classify_place(text, cfg, title_text=None):
    """Return (city, tier, venue_name_or_None, how) where how says which rule
    fired, so a wrong answer can be traced without guessing.

    A venue name is trusted wherever it appears, headline or summary. The bare
    words "Broadway" and "Off-Broadway" are only trusted in the headline:
    BroadwayWorld puts its own name and boilerplate in every description, so
    reading those as a location filed a Maryland community theatre production
    of Steel Magnolias as Broadway.
    """
    venue = match_venue(text, cfg["venues"])
    if venue:
        return venue["city"], venue["tier"], venue["name"], "venue"

    rule = match_fallback(title_text if title_text is not None else text,
                          cfg["fallbacks"]["rules"])
    if rule:
        return rule["city"], rule["tier"], None, "words"

    return None, None, None, "none"


def classify_type(text):
    for name, phrases in TYPE_RULES:
        for p in phrases:
            if p in text:
                return name, p
    return None, None


# Words that look like part of a name but are not.
#
# This list carries more weight than it looks. Trade outlets title-case every
# word in a headline, so "Will Be Joined By" and "And Be Present" arrive
# looking exactly like "Bernadette Peters". Without a thorough stoplist the
# junk fills the per-story lookup budget and the real names never get asked
# about - which is precisely how the first run found zero celebrities in a
# batch that included Bernadette Peters and Audra McDonald.
NAME_STOPWORDS = {
    # places, institutions, the vocabulary of the beat
    "broadway", "off-broadway", "theatre", "theater", "musical", "play", "plays",
    "new", "york", "chicago", "london", "west", "end", "national", "american",
    "north", "tour", "touring", "company", "productions", "production",
    "season", "premiere", "revival", "concert", "concerts", "benefit", "gala",
    "street", "avenue", "center", "centre", "stage", "studio", "club", "hotel",
    "tony", "awards", "award", "drama", "desk", "olivier", "pulitzer", "grammy",
    "emmy", "oscar", "obie",
    # articles, conjunctions, prepositions, auxiliaries
    "the", "a", "an", "and", "or", "but", "of", "in", "at", "on", "from",
    "with", "for", "by", "as", "to", "into", "over", "after", "before",
    "is", "are", "was", "were", "be", "been", "will", "has", "have", "had",
    "its", "his", "her", "their", "this", "that", "more", "all",
    # headline verbs and nouns
    "joins", "joined", "join", "leads", "lead", "star", "stars", "starring",
    "announce", "announces", "announced", "sets", "set", "returns", "return",
    "opens", "open", "opening", "closes", "close", "closing", "extends",
    "begins", "begin", "beginning", "launches", "launch", "reveals", "reveal",
    "shares", "share", "features", "featuring", "honor", "honors", "honoring",
    "delaying", "delay", "casting", "cast", "replaces", "takes", "takes",
    "makes", "make", "presents", "present", "brings", "bring", "gets", "get",
    "watch", "listen", "read", "look", "first", "exclusive", "breaking",
    "photos", "photo", "video", "scene", "cover", "weekly", "daily",
    "childhood", "summers", "crossword", "spotlight", "anniversary",
    "album", "christmas", "series", "start", "dates", "date", "tickets",
    # pronouns and titles of address, which sit next to real names constantly
    "your", "my", "our", "you", "we", "he", "she", "they", "it", "who",
    "st", "mr", "mrs", "ms", "dr", "sir", "dame", "lord",
    # calendar
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
}

NAME_PARTICLES = {"de", "van", "von", "della", "di", "la", "le", "du", "del"}

# Punctuation that ends a name even when the next word is capitalized:
# "Maryann Plunkett, Jay O. Sanders" is two people, not one four-word name.
BREAK_AFTER = set(",;:!?—–()[]\"“”")

STRIP_EDGES = ".,;:!?\"'()[]{}‘’“”"

# A middle initial, after edge punctuation has been stripped: "O." is "O".
INITIAL_RE = re.compile(r"^[A-Z]$")

# A possessive ends a name rather than continuing it. Without this,
# "Broadway's School Girls" and "The Pitt's Lucas Iverson" come back as
# single candidates and the actual name inside them is never looked up.
POSSESSIVE_RE = re.compile(r"[’']s$")


def _looks_like_name_word(tok):
    """A capitalized word that is not a stopword and not SHOUTED.

    The all-caps test matters more than it sounds: BroadwayWorld prints show
    titles in full caps, so without it "24 HOUR PLAYS ON BROADWAY" offers up
    three perfectly good-looking surnames.
    """
    if len(tok) < 2:
        return False
    if not tok[0].isupper():
        return False
    if not any(ch.islower() for ch in tok):
        return False
    if tok.lower() in NAME_STOPWORDS:
        return False
    return True


def extract_names(title):
    """Runs of capitalized words that look like a person's name.

    Scanned token by token rather than matched with one regex, because a
    greedy pattern swallows the word in front of the name and then chokes on
    it: "to Honor Thomas Kail" came back as the single candidate "Honor
    Thomas Kail", which failed the stopword test and lost Thomas Kail with it.

    Deliberately shallow past that. This only proposes candidates; Wikidata
    decides which are real people worth listing. A false positive costs one
    cached lookup, a false negative loses a name entirely, so it leans
    towards proposing.
    """
    tokens = str(title or "").split()
    candidates = []
    run = []

    def flush():
        if len(run) >= 2:
            name = " ".join(run[:3])
            if name not in candidates:
                candidates.append(name)
        run.clear()

    for raw in tokens:
        tok = raw.strip(STRIP_EDGES)
        breaks = bool(raw) and raw[-1] in BREAK_AFTER

        if not tok:
            flush()
            continue

        # A possessive ends a name, but the word carrying it is still part of
        # that name: "Aubrey Plaza's Broadway debut" is about Aubrey Plaza,
        # while "Broadway's School Girls" is not about anyone. So strip the
        # 's, keep the word if it stands up on its own, then close the run -
        # whatever follows a possessive belongs to a different phrase.
        bare = raw.strip(STRIP_EDGES.replace("'", "").replace("’", ""))
        if POSSESSIVE_RE.search(bare):
            owner = POSSESSIVE_RE.sub("", bare).strip(STRIP_EDGES)
            if _looks_like_name_word(owner):
                run.append(owner)
            flush()
            continue

        if _looks_like_name_word(tok):
            run.append(tok)
        elif run and (INITIAL_RE.match(tok) or tok.lower() in NAME_PARTICLES):
            # Middle initials and nobiliary particles continue a name but
            # never start one.
            run.append(tok)
        else:
            flush()
            continue

        if breaks:
            flush()

    flush()
    return candidates


def show_title(text_original):
    """A quoted or title-cased show name, if the headline offers one.

    Used for clustering rather than display, so a near miss is cheap: two
    stories about the same show only need to agree with each other.
    """
    for pattern in (r"[‘’']([^'‘’]{2,60})[’']",
                    r'[“”"]([^"“”]{2,60})[”"]'):
        m = re.search(pattern, str(text_original or ""))
        if m:
            return m.group(1).strip()
    # ALL CAPS show titles, which BroadwayWorld uses constantly
    m = re.search(r"\b([A-Z][A-Z0-9'&!. ]{3,40})\b", str(text_original or ""))
    if m:
        t = m.group(1).strip()
        if len(t.split()) <= 8 and t.upper() == t:
            return t.title()
    return None
