---
title: I built a theater news page with zero paid services
date: 2026-08-28
description: RSS feeds, a rules engine, Wikidata for fame scores, and a scheduled job that runs four times a day. Here is how the pieces fit.
tags:
  - projects
  - news
draft: true
---

Placeholder copy. Rewrite this post before taking the draft flag off. Keep the
technical detail honest and skip anything that names a private service or key.

## The problem

Say what was missing: a single page that shows who just got cast in New York
and Chicago, without a paid news subscription and without checking a dozen
sites by hand.

## The pieces

- **Feeds.** A list of free RSS sources, plus search queries that catch the
  outlets that block direct feeds.
- **Rules.** Venue lists give a story its city, and a short phrase list gives
  it a type: casting, opening, transfer, closing.
- **Names.** A public knowledge base supplies the "who" and a rough sense of
  how widely known they are.
- **Schedule.** The whole thing runs a few times a day and writes its results
  into the site.

## What it gets wrong

The interesting half of the post. Describe the misses honestly - nicknames in
headlines, local outlets covering out-of-town shows - and what the fix is.

## What it cost

Nothing but the time to build it. Spell out why that was a requirement rather
than a nice result.
