---
name: video
description: "Make or edit a video on this box and hand the user a link: trim, cut, join, compress, make it vertical (9:16 for Reels/TikTok/Shorts), platform exports, GIF preview, thumbnail, pull the audio out, captions/subtitles, a caption or the user's name on it, title cards, or a short clip from scratch. Use when the user texts you a video (MMS), sends a video link, asks for any of the above, or asks for 'a video' at all. The editing engine is the `ffmpeg-skill` skill on this box (42 local FFmpeg tools); this skill owns the box side — where the input is, how to run the tools here, and delivery via the present-file link contract."
---

# Video (ffmpeg-skill on the box → link)

The editor is the **`ffmpeg-skill`** skill installed next to this one — read its `SKILL.md` for the request→script table and its workflow rules (probe first, prefer lossless, chain in order, `check.py` the deliverable, `look.py` the picture). It needs only the `ffmpeg`/`ffprobe` and `python3` that are already on this box; nothing installs and nothing *can* install (read-only image). If a script fails with `kind: missing_tool`, a HUMAN must fix the box — report the exact error and stop.

## How to run the tools here

Run shell commands from `execute_code` with `subprocess` — never `read_file`/`write_file` on a video (binary; it corrupts the file and floods your context):

```python
import subprocess
r = subprocess.run(["bash", "-c", CMD], capture_output=True, text=True)
print(r.returncode, r.stdout[-3000:], r.stderr[-1500:])
```

Start every `CMD` with this preamble (the paths are literal on this box):

```bash recipe=vars
SK=/opt/data/skills/ffmpeg-skill
WORK=/opt/data/work/video; mkdir -p "$WORK"; cd "$WORK"
ART=/opt/data/artifacts; mkdir -p "$ART"
export FFMPEG_SKILL_NO_OVERWRITE=1 PYTHONWARNINGS=ignore
```

- `SK` is the ffmpeg-skill directory; every tool is `python3 $SK/scripts/<name>.py …` exactly as its `SKILL.md` shows with `<skill-dir>` = `$SK`.
- `WORK` is your scratch (persistent disk). `ART` is `ARTIFACT_DIR` — files written there are served publicly at `ARTIFACT_BASE_URL/<name>` (both values are in your operating context, `SOUL.md`). Write the FINAL file straight into `ART`.
- `FFMPEG_SKILL_NO_OVERWRITE=1` is the setting ffmpeg-skill recommends for agents (an existing output is refused instead of clobbered; `--overwrite` is the one way to replace). `PYTHONWARNINGS=ignore` silences a harmless `SyntaxWarning` the scripts print on Python 3.13.
- Prefer `--json-brief` on every writing step and read `status`/`summary` from it; never parse the human summary line.
- Before a job, check free space: `df -P /opt/data | awk 'NR==2{print $4}'` prints free KB. Below `512000` (500 MB), stop and tell the user the box is out of space.

## 1. Get the input

- **The user texted a video (MMS).** The turn note tells you where it is: `It is saved at: /tmp/telnyx_mms_<random>.mp4` (or `.3gp`). Use that path directly. Inbound MMS is capped at 5 MB by the carrier plugin — if they need to send something bigger, ask for a link (Google Drive/Dropbox/iCloud share; YouTube is NOT downloadable here — there is no `yt-dlp` on this box).
- **The user sent a link.** Download it into `WORK` (200 MB cap):

```bash recipe=download
curl -sSL --max-time 120 --max-filesize 209715200 -o "$WORK/in.mp4" "$URL"
```

- **A file you already made** under `/opt/data` — use its path.
- **No input — make one from scratch** (a placeholder or a test clip). This is the ONE raw `ffmpeg` command in this skill: ffmpeg-skill has no source generator with audio (`background.py` is silent, and the `reels`/`tiktok`/`shorts` templates refuse a silent input at their loudness stage), so generate a 5 s 1280×720 test pattern with a 440 Hz tone, then edit it with the tools like any other input:

```bash recipe=synth
ffmpeg -hide_banner -loglevel error -y -f lavfi -i testsrc2=size=1280x720:rate=30 -f lavfi -i sine=frequency=440:sample_rate=48000 -t 5 -c:v libx264 -preset veryfast -crf 23 -pix_fmt yuv420p -c:a aac -b:a 96k -movflags +faststart "$WORK/in.mp4"
```

For a title card on it, add `graphics.py "$WORK/in.mp4" --template title --title "…" --duration 5 -o "$WORK/titled.mp4" --json-brief`. If a user's own clip is silent, `render.py --template …` will refuse at its loudness stage — use `export.py --preset reels` (or another preset) instead, which does not normalise loudness.

Then probe before planning — if it is not a media file, say what you received and ask for a video:

```bash recipe=probe
python3 "$SK/scripts/probe.py" "$WORK/in.mp4" --json
```

## 2. Do the edit (ffmpeg-skill)

Follow ffmpeg-skill's `SKILL.md`; these are the calls this box's users ask for most, written for `$WORK/in.mp4` (adapt the input path; `START`/`END` are seconds or `mm:ss`; `TEXT` is the caption):

**Vertical 9:16 for Reels / TikTok / Shorts, delivery-checked** (one template run does fit → loudness → export → check):

```bash recipe=reels
python3 "$SK/scripts/render.py" --template reels "$WORK/in.mp4" -o "$ART/$NAME.mp4" --json-brief
```

**Trim** (frame-accurate):

```bash recipe=trim
python3 "$SK/scripts/cut.py" "$WORK/in.mp4" --start "$START" --end "$END" --accurate -o "$ART/$NAME.mp4" --json-brief
```

**Join clips** (paths in order; add `--transition fade --duration 0.5` for a crossfade):

```bash recipe=join
python3 "$SK/scripts/join.py" "$WORK/a.mp4" "$WORK/b.mp4" -o "$ART/$NAME.mp4" --json-brief
```

**Caption / name overlay** (text centred at the bottom for the whole clip; named positions are `top-left top top-right left center right bottom-left bottom bottom-right`, or `X,Y`):

```bash recipe=overlay
python3 "$SK/scripts/overlay.py" "$WORK/in.mp4" --text "$TEXT" --position bottom -o "$ART/$NAME.mp4" --json-brief
```

**Burn subtitles from an SRT** (`caption.py --transcribe` is NOT available here — no whisper on the box; ask for the text or a timed file, never invent dialogue):

```bash recipe=caption
python3 "$SK/scripts/caption.py" "$WORK/in.mp4" --srt "$WORK/subs.srt" -o "$ART/$NAME.mp4" --json-brief
```

**GIF preview**:

```bash recipe=gif
python3 "$SK/scripts/export.py" "$WORK/in.mp4" --preset gif -o "$ART/$NAME.gif" --json-brief
```

**Extract the audio as MP3** (an audio-only output path drops the video):

```bash recipe=audio
python3 "$SK/scripts/audio.py" "$WORK/in.mp4" -o "$ART/$NAME.mp3" --json-brief
```

**Thumbnail** (one frame at `AT` seconds; `look.py` names the PNG it wrote):

```bash recipe=thumbnail
python3 "$SK/scripts/look.py" "$WORK/in.mp4" --at "$AT" --no-timecode -o "$ART/$NAME.png"
```

**Compress / plain web MP4** (YouTube preset = 1080p H.264/AAC, BT.709 tags, faststart):

```bash recipe=export
python3 "$SK/scripts/export.py" "$WORK/in.mp4" --preset youtube -o "$ART/$NAME.mp4" --json-brief
```

**Check a deliverable** for a platform before you send it (a template run already did this):

```bash recipe=check
python3 "$SK/scripts/check.py" "$ART/$NAME.mp4" --platform reels
```

Anything else — silence removal, speed change, LUTs, HDR→SDR, loudness, lower-thirds, multicam, scene detection, batch — is in ffmpeg-skill's table; use its scripts, never a raw `ffmpeg` command.

## 3. Deliver — the present-file link contract

1. Name the output for a human, hyphenated, with the right extension, distinctive enough not to overwrite someone else's file: `Open-House-Teaser-Anderson-2026-09.mp4`, `Listing-Walkthrough-Vertical.mp4`, `Intro-Thumbnail.png`. That name is `$NAME` above.
2. Write it to `ART/<that-name>` (that IS the `present-file` procedure — the file is already in `ARTIFACT_DIR`).
3. Confirm the writing step's `--json-brief` says `"status": "completed"` and `"verified": true` (or `probe.py` the file), then delete your intermediates in `WORK`.
4. Reply with ONE short line and the link `ARTIFACT_BASE_URL/<name>` — for example: `Here's the vertical cut: https://…/Listing-Walkthrough-Vertical.mp4`. Under 600 characters; it is a text message. Never reveal `WORK`, `ART`, `SK`, or any local path.

## Rules

- **Never** `read_file`/`write_file` a media file. Media moves only via the ffmpeg-skill scripts, `curl`, `cp`, `mv` inside `subprocess`.
- **One corrected retry at most.** ffmpeg-skill reports failures as JSON with `kind` (`input`, `missing_tool`, `timeout`, …) and `message`; if the message names the fix (wrong flag, missing `-o` extension), fix it once. Otherwise stop, tell the user the `message` in plain words, and ask how they want to proceed. Never loop on variations.
- Do not install, download, or build tools. Do not use `terminal`-style tools that are not offered to you.
- Do not upload the user's video anywhere except `ART`, and do not keep a copy after delivery beyond what is in `ART`.
- Keep deliverables as ffmpeg-skill's presets produce them (H.264/AAC MP4, or GIF/PNG/MP3 for those recipes) — the link is opened on a phone.

## Provenance

`ffmpeg-skill` on this box is a verbatim copy of `SKILL.md`, `LICENSE`, `scripts/`, `templates/` and `references/` from https://github.com/kajisho5/ffmpeg-skill at commit `cecf37ca8194a83bacf5a564700112f73656c26d` (v1.17.3, MIT, © kajisho5). Do not edit it; update by re-copying and bumping the commit here and in the skills repo's test.
