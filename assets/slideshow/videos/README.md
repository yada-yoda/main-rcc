# Slideshow videos

Drop short video clips here for use in the hero slideshow.

## Recommended specs

- **Format**: MP4 (H.264), `faststart` enabled so it starts playing
  before fully buffered
- **Resolution**: 1920&times;1080 (matches the photo dimensions)
- **Duration**: 8&ndash;15 seconds per clip (matches the photo rotation
  interval, so it loops cleanly alongside the photo slides)
- **Audio**: stripped (the hero is muted by design &mdash; quotes carry
  the message)
- **File size**: under ~5 MB per clip so first paint stays fast on
  mobile

## How to encode

Recipe used for the current clips (720p, audio kept, ~5MB each from
~25MB originals — 80% smaller, visually fine as background):

```
ffmpeg -i source.mp4 \
  -vf "scale=-2:720" \
  -c:v libx264 -preset slow -crf 26 -pix_fmt yuv420p \
  -c:a aac -b:a 96k \
  -movflags +faststart \
  output.mp4
```

If you want a higher-quality version (1080p, audio kept, ~15MB):

```
ffmpeg -i source.mp4 \
  -c:v libx264 -preset slow -crf 24 -pix_fmt yuv420p \
  -c:a aac -b:a 96k \
  -movflags +faststart \
  output.mp4
```

Strip audio (smaller, but the hero volume control becomes irrelevant):
append `-an` before the output filename.

## Wiring a video into the slideshow

Two paths:

1. **Replace an existing photo slot** &mdash; in `index.html`, find
   `EDIT: hero-slides` and swap one of the `<div class="hero-slide" style="background-image:url(&hellip;)"></div>`
   entries for a `<video class="hero-slide" ...>` element.
2. **Ask Claude to do it** &mdash; once a clip lands here, mention the
   filename and Claude will wire it in (with the right autoplay,
   muted, loop, playsinline attributes) and keep the paired-quote
   rotation aligned.

## Naming

Use short descriptive names: `reel-cut.mp4`, `improv-set.mp4`,
`on-set.mp4`. Numbers up front (e.g. `01-reel.mp4`) if you want to
control rotation order via filename sorting.
