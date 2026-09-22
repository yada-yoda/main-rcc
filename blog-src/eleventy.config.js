const site = require("./src/_data/site.json");

/**
 * Drafts.
 *
 * `draft: true` in a post's front matter keeps it out of the published
 * build - no page, no listing, no feed entry, no sitemap line. Local
 * previews (`npm run serve`) show drafts so a post can be read in place
 * before the flag comes off, and BLOG_DRAFTS=1 forces the same for a
 * one-off local build. The GitHub Action sets neither, so what lands on
 * rizzo.cc is published posts only.
 */
const showDrafts =
  process.env.BLOG_DRAFTS === "1" || process.env.ELEVENTY_RUN_MODE === "serve";

/**
 * Eleventy configuration for rizzo.cc/blog.
 *
 * The built site is written straight into ../blog, which is the folder
 * GitHub Pages serves at https://rizzo.cc/blog/. Nothing here writes
 * outside that folder, so the acting site at the domain root is never
 * touched by a blog build.
 *
 * Everything that identifies the section - name, version, base URL,
 * analytics id - lives in src/_data/site.json so a release means editing
 * one file. See the README changelog.
 */
module.exports = function (eleventyConfig) {
  eleventyConfig.addPassthroughCopy({ "src/css": "css" });
  // src/static holds files that must sit at /blog/<name>: og.png and the
  // apple touch icon are referenced by absolute URL from the page head.
  eleventyConfig.addPassthroughCopy({ "src/static": "." });

  // ---- Collections -------------------------------------------------------
  eleventyConfig.addCollection("posts", (api) =>
    api
      .getFilteredByTag("post")
      .filter((item) => !item.data.draft || showDrafts)
      .sort((a, b) => b.date - a.date)
  );

  // Every tag used by a published post, alphabetical, with its post count.
  // "post" is the collection tag itself and never shown.
  eleventyConfig.addCollection("tagList", (api) => {
    const counts = new Map();
    api
      .getFilteredByTag("post")
      .filter((item) => !item.data.draft || showDrafts)
      .forEach((item) => {
        (item.data.tags || [])
          .filter((t) => t !== "post")
          .forEach((t) => counts.set(t, (counts.get(t) || 0) + 1));
      });
    return [...counts.entries()]
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => a.name.localeCompare(b.name));
  });

  // ---- URL helpers -------------------------------------------------------
  // The blog is a folder on an existing domain, so every internal link needs
  // the /blog prefix and every feed or meta tag needs the full absolute URL.
  const href = (path) => {
    const p = String(path || "/");
    return (site.pathPrefix + (p.startsWith("/") ? p : "/" + p)).replace(/\/{2,}/g, "/");
  };
  eleventyConfig.addFilter("href", href);
  eleventyConfig.addFilter("absUrl", (path) => site.baseUrl + href(path));

  // ---- Dates -------------------------------------------------------------
  eleventyConfig.addFilter("isoDate", (d) => new Date(d).toISOString());
  eleventyConfig.addFilter("stampDate", (d) => new Date(d).toISOString().slice(0, 10));
  eleventyConfig.addFilter("shortDate", (d) =>
    new Date(d).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      timeZone: "UTC",
    })
  );
  // RSS wants RFC 822. toUTCString is exactly that format.
  eleventyConfig.addFilter("rssDate", (d) => new Date(d).toUTCString());

  // ---- Text --------------------------------------------------------------
  const stripTags = (s) => String(s || "").replace(/<[^>]*>/g, " ");

  eleventyConfig.addFilter("readingTime", (input) => {
    const words = stripTags(input).trim().split(/\s+/).filter(Boolean).length;
    return Math.max(1, Math.ceil(words / site.wordsPerMinute));
  });

  eleventyConfig.addFilter("jsonify", (v) => JSON.stringify(v));

  // Tag slugs are used in URLs, so they are lowercase and dash separated.
  eleventyConfig.addFilter("tagSlug", (t) =>
    String(t)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
  );

  return {
    pathPrefix: site.pathPrefix + "/",
    dir: {
      input: "src",
      output: "../blog",
      includes: "_includes",
      data: "_data",
    },
    markdownTemplateEngine: "njk",
    htmlTemplateEngine: "njk",
    templateFormats: ["njk", "md"],
  };
};
