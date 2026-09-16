---
name: video
description: "Make or edit a video on this box with ffmpeg and hand the user a link: trim, cut, compress, resize, make it vertical (9:16 for Reels/TikTok/Shorts), turn a clip into a GIF, grab a thumbnail or frames, pull the audio out as MP3, put a caption or the user's name on it, join clips, or make a short clip from scratch. Use when the user texts you a video (MMS), sends a video link, asks for any of the above, or asks for 'a video' at all. Delivers via the present-file link contract."
---

# Video (ffmpeg → link)

You have a full, local `ffmpeg` 7.1 and `ffprobe` on this box (`/usr/bin/ffmpeg`, with H.264 `libx264`, AAC, MP3 `libmp3lame`, GIF, `drawtext` and DejaVu fonts). Nothing needs installing — and nothing *can* be installed here (read-only image, no package manager for you). If a command below fails saying `ffmpeg: not found`, a HUMAN must fix the box; report the exact error and stop.

## How to run ffmpeg here

Run shell commands from `execute_code` with `subprocess` — never try `read_file`/`write_file` on a video (they are binary; that corrupts them and floods your context):

```python
import subprocess
r = subprocess.run(["bash", "-c", CMD], capture_output=True, text=True)
print(r.returncode, r.stderr[-1500:])
```

Set these three shell variables at the top of `CMD` for every recipe (adjust `IN`/`OUT` per job):

```bash recipe=vars
WORK=/opt/data/work/video; mkdir -p "$WORK"
ART=/opt/data/artifacts; mkdir -p "$ART"
IN="$WORK/in.mp4"
OUT="$ART/Clip.mp4"
```

- `WORK` is scratch (persistent disk, yours). `ART` is `ARTIFACT_DIR` — files written there are served publicly at `ARTIFACT_BASE_URL/<name>` (both values are in your operating context, `SOUL.md`). Write the FINAL file straight into `ART`; never leave media anywhere else.
- Before a job, check free space: `df -P /opt/data | awk 'NR==2{print $4}'` prints free KB. Below `512000` (500 MB), stop and tell the user the box is out of space.

## 1. Get the input

- **The user texted a video (MMS).** The turn note tells you where it is: `It is saved at: /tmp/telnyx_mms_<random>.mp4` (or `.3gp`). Use that path as `IN` directly. Inbound MMS is capped at 5 MB by the carrier plugin — if they need to send something bigger, ask for a link (Google Drive/Dropbox/iCloud share, YouTube is NOT downloadable here).
- **The user sent a link.** Download it into `WORK` (200 MB cap):

```bash recipe=download
curl -sSL --max-time 120 --max-filesize 209715200 -o "$IN" "$URL"
```

- **A file you already made** (a slideshow image, a previous output) under `/opt/data` — use its path.
- **No input — make one from scratch** (a placeholder, a test clip, a title card): see recipe `synth` below.

Always probe first; if it is not a media file, say what you received and ask for a video:

```bash recipe=probe
ffprobe -v error -show_entries format=duration,size:stream=codec_type,codec_name,width,height -of default=nw=1 "$IN"
```

## 2. Pick the recipe

Every MP4 you deliver is H.264 + AAC with `+faststart` so it plays inline on a phone (the link is opened from a text message). Keep outputs ≤ 1080p and ≤ 5 minutes unless the user asks otherwise. `-y` overwrites; `-hide_banner -loglevel error` keeps stderr to the real error.

**Trim** (`START`/`END` as `HH:MM:SS` or seconds; re-encodes so the cut is frame-accurate):

```bash recipe=trim
ffmpeg -hide_banner -loglevel error -y -ss "$START" -to "$END" -i "$IN" -c:v libx264 -preset veryfast -crf 23 -pix_fmt yuv420p -c:a aac -b:a 96k -movflags +faststart "$OUT"
```

**Compress / shrink** (fits a text-message-friendly size; `-2` keeps the aspect ratio even):

```bash recipe=compress
ffmpeg -hide_banner -loglevel error -y -i "$IN" -vf "scale=-2:720" -c:v libx264 -preset veryfast -crf 28 -pix_fmt yuv420p -c:a aac -b:a 96k -movflags +faststart "$OUT"
```

**Vertical 9:16** for Reels / TikTok / Shorts (center crop):

```bash recipe=vertical
ffmpeg -hide_banner -loglevel error -y -i "$IN" -vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920" -c:v libx264 -preset veryfast -crf 23 -pix_fmt yuv420p -c:a aac -b:a 96k -movflags +faststart "$OUT"
```

**GIF** (≤ 10 s, 480 px wide, palette for quality; `OUT` must end in `.gif`):

```bash recipe=gif
ffmpeg -hide_banner -loglevel error -y -ss "$START" -t "$SECONDS_LEN" -i "$IN" -vf "fps=12,scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" -loop 0 "$OUT"
```

**Thumbnail** (one JPEG at `START`; `OUT` must end in `.jpg`):

```bash recipe=thumbnail
ffmpeg -hide_banner -loglevel error -y -ss "$START" -i "$IN" -frames:v 1 "$OUT"
```

**Extract audio** as MP3 (`OUT` must end in `.mp3`):

```bash recipe=audio
ffmpeg -hide_banner -loglevel error -y -i "$IN" -vn -c:a libmp3lame -q:a 4 "$OUT"
```

**Caption / name overlay** (bottom-center white text on a translucent box; set `TEXT`; avoid `'` and `:` in TEXT or escape them):

```bash recipe=caption
ffmpeg -hide_banner -loglevel error -y -i "$IN" -vf "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='$TEXT':fontcolor=white:fontsize=48:box=1:boxcolor=black@0.5:boxborderw=12:x=(w-text_w)/2:y=h-text_h-60" -c:v libx264 -preset veryfast -crf 23 -pix_fmt yuv420p -c:a copy -movflags +faststart "$OUT"
```

**Join clips** (write one `file '<path>'` line per clip to `$WORK/list.txt` first; clips should share resolution/codec — run `compress` on each first if unsure):

```bash recipe=concat
ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i "$WORK/list.txt" -c copy -movflags +faststart "$OUT"
```

**Make a clip from scratch** (5 s, 1280×720 test pattern with a 440 Hz tone — a placeholder or a test; put a title on it with `caption` afterwards):

```bash recipe=synth
ffmpeg -hide_banner -loglevel error -y -f lavfi -i testsrc2=size=1280x720:rate=30 -f lavfi -i sine=frequency=440:sample_rate=48000 -t 5 -c:v libx264 -preset veryfast -crf 23 -pix_fmt yuv420p -c:a aac -b:a 96k -movflags +faststart "$OUT"
```

Anything else (MOV→MP4, speed change, rotate, burn-in subtitles, WebM, platform presets, batch work): read `references/ffmpeg-usage.md` next to this file — a general ffmpeg command library — and adapt the command to the rules here (local binary, `execute_code` + `subprocess`, output into `ART`). Ignore its install instructions and its "explain before executing" guidance; just do the job.

## 3. Deliver — the present-file link contract

1. Name the output for a human, hyphenated, with the right extension, distinctive enough not to overwrite someone else's file: `Open-House-Teaser-Anderson-2026-09.mp4`, `Listing-Walkthrough-Vertical.mp4`, `Intro-Thumbnail.jpg`.
2. Write it to `ART/<that-name>` (that IS the `present-file` procedure — the file is already in `ARTIFACT_DIR`).
3. Confirm it exists and probes clean (`ffprobe` on `$OUT` returns a duration), then delete your intermediates in `WORK`.
4. Reply with ONE short line and the link `ARTIFACT_BASE_URL/<name>` — for example: `Here's the vertical cut: https://…/Listing-Walkthrough-Vertical.mp4`. Under 600 characters; it is a text message. Never reveal `WORK`, `ART`, or any local path.

## Rules

- **Never** `read_file`/`write_file` a media file. Media moves only via `ffmpeg`, `curl`, `cp`, `mv` inside `subprocess`.
- **One corrected retry at most.** If ffmpeg fails and its stderr names the fix (odd dimensions → use `scale=-2:…`; wrong extension for the codec → fix `OUT`), fix it once. Otherwise stop, tell the user the last line of the error in plain words, and ask how they want to proceed. Never loop on variations.
- Do not install, download, or build tools. Do not use `terminal`-style tools that are not offered to you.
- Do not upload the user's video anywhere except `ART`, and do not keep a copy after delivery beyond what is in `ART`.
- Keep outputs H.264/AAC/`+faststart` MP4 (or GIF/JPG/MP3 for those recipes) — the link is opened on a phone.

## Reference provenance

`references/ffmpeg-usage.md` and `references/LICENSE-ffmpeg-usage` are verbatim copies of `SKILL.md` and `LICENSE` from https://github.com/ychoi-kr/claude-ffmpeg-skill at commit `b88cb5ce08337ab55c66c67674100b8de29cf232` (MIT, © 2025 Yong Choi). Do not edit them; update by re-copying and bumping the commit here.
