/**
 * Shared front matter for everything in src/posts.
 *
 * A post file is named YYYY-MM-DD-slug.md so the folder reads in order on
 * disk, but the published URL is /blog/slug/ - the date is already on the
 * page and does not need to be in the address.
 */
const showDrafts =
  process.env.BLOG_DRAFTS === "1" || process.env.ELEVENTY_RUN_MODE === "serve";

const WORDS_PER_MINUTE = require("../_data/site.json").wordsPerMinute;

const isHidden = (data) => Boolean(data.draft) && !showDrafts;

module.exports = {
  layout: "layouts/post.njk",
  tags: ["post"],
  draft: false,
  eleventyComputed: {
    // A hidden draft writes no file at all, so nothing is published by
    // accident and nothing can be found by guessing the URL.
    permalink: (data) =>
      isHidden(data)
        ? false
        : "/" + String(data.page.fileSlug).replace(/^\d{4}-\d{2}-\d{2}-/, "") + "/",
    eleventyExcludeFromCollections: (data) => isHidden(data),
    // Counted from the Markdown source, which is close enough for a badge
    // and avoids depending on render order.
    readingTime: (data) => {
      const words = String(data.page.rawInput || "")
        .replace(/<[^>]*>/g, " ")
        .trim()
        .split(/\s+/)
        .filter(Boolean).length;
      return Math.max(1, Math.ceil(words / WORDS_PER_MINUTE));
    },
  },
};
