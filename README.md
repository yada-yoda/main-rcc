# main-rcc

Production content for **rizzo.cc**, served by GitHub Pages from `main`.

Two things live here and they do not overlap:

| Path | What it is | Who writes it |
|---|---|---|
| `/` (root) | The acting site. `index.html`, `resources.html`, `reel.html`, `assets/`, `sitemap.xml`, `robots.txt` | Mirrored in from the `dev` repo by its sync workflow. **Never edit these by hand** - the next sync overwrites them. |
| `/blog` | The blog at rizzo.cc/blog | Built here from `blog-src/` by `.github/workflows/build-blog.yml` |
| `news-src/` | The Stage Wire news ingest | Runs itself four times a day via `.github/workflows/news-ingest.yml` |

`.nojekyll` at the root turns GitHub's Jekyll pass off. Without it Jekyll would
render the Eleventy sources in `blog-src/` as extra pages.

## Writing a blog post

1. Add `blog-src/src/posts/YYYY-MM-DD-slug.md` with front matter:

   ```yaml
   ---
   title: The headline
   date: 2026-09-22
   description: One sentence. It is the list blurb, the share text and the feed summary.
   tags:
     - comedy
   draft: true
   ---
   ```

2. Push. The Build blog workflow runs Eleventy and commits `blog/`.

The published URL drops the date: `2026-09-22-the-headline.md` becomes
`https://rizzo.cc/blog/the-headline/`.

`draft: true` keeps a post out of the build completely - no page, no listing,
no feed entry, no sitemap line. Drafts are visible locally:

```
cd blog-src
npm install
npm run serve      # http://localhost:8080/blog/ , drafts included
```

A one-off local build with drafts is `BLOG_DRAFTS=1 npx @11ty/eleventy`.

Everything that identifies the section - version, headline, analytics id -
lives in `blog-src/src/_data/site.json`. The share card and touch icon are
regenerated from it with `python .scripts/make-images.py`.

### Sitemaps

The blog keeps its own sitemap at `/blog/sitemap.xml`. The root `/sitemap.xml`
belongs to the acting site and is mirrored over on every acting edit, so blog
URLs cannot be merged into it and survive. Search engines pick both up from the
`Sitemap:` lines in `robots.txt`.

## The news ingest

`news-src/` collects theatre casting news from free RSS feeds and files each
story by city, tier and type. It runs on a schedule and needs no key, no
account and no paid service.

```
news-src/
  feeds.json      the sources: Google News queries plus direct outlet feeds
  venues.json     Broadway / Off-Broadway / Chicago houses -> city and tier
  classify.py     the rules: what is theatre news, where, and what kind
  people.py       Wikidata lookups - is this a performer, how widely known
  wire.py         fetching, date parsing, RSS and Atom reading
  ingest.py       the pipeline that ties it together
  check_feeds.py  source health report
  overrides.json  manual corrections, applied last, always winning
  data/           stories.json and the Wikidata name cache
```

Useful commands, run from `news-src/`:

```
python check_feeds.py                          which sources still answer
python ingest.py --dry-run --no-people --fast  classify without writing
python ingest.py --dry-run --show 10           same, print the top stories
python ingest.py                               the real run, writes data/
```

**Nothing is invented.** A story's summary is the outlet's own feed
description trimmed to two sentences, kept as a quote with the outlet named.
Article body text is never copied.

**Unsure means off the page.** A story missing a city or a type gets
`status: review` and stays out of the published set. A story with neither is
dropped as off-topic - that is usually a search query catching the wrong
Paramount.

**Corrections are one line.** Add the story id to `overrides.json` with
`{"hide": true}` or with the fields to correct. Overrides are applied after
the rules and always win, so nothing needs a code change to be fixed.

**The fame score** next to a name is how many language editions of Wikipedia
have an article about that person. It is crude on purpose: public, free, and
hard to game. Names below the threshold still appear in the story, they just
do not get a celebrity chip.

## Changelog

### Blog v0.1.0 - 2026-09-22

First release of rizzo.cc/blog.

The acting site is a single-purpose page for casting people, and there was
nowhere on the domain to write anything longer than a credit. The blog is a
folder rather than a subdomain so what it earns in search credits the same
domain as the acting pages, and it carries its own "Broadsheet" look - paper,
navy ink, Georgia headlines - so a visitor arriving from a search result knows
it is a different room in the same house.

Included: post list, post pages, tag pages, a full-text RSS feed, reading time,
per-post share cards, its own sitemap, and a draft flag so unfinished posts
never reach the build. Three starter posts ship as drafts, with placeholder
copy to be rewritten before they go up.

Nothing on the acting pages changed.
