# main-rcc

Production content for **rizzo.cc**, served by GitHub Pages from `main`.

Two things live here and they do not overlap:

| Path | What it is | Who writes it |
|---|---|---|
| `/` (root) | The acting site. `index.html`, `resources.html`, `reel.html`, `assets/`, `sitemap.xml`, `robots.txt` | Mirrored in from the `dev` repo by its sync workflow. **Never edit these by hand** - the next sync overwrites them. |
| `/blog` | The blog at rizzo.cc/blog | Built here from `blog-src/` by `.github/workflows/build-blog.yml` |

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
