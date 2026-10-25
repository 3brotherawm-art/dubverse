# DubVerse — Video Translator & AI Dubbing Studio

Users upload a video, DubVerse transcribes the speech (Whisper), translates it,
and dubs it back with a neural voice **matched to the speaker** — a male speaker
gets a male voice, a female speaker gets a female voice.

## Features
- Upload MP4 / MOV / MKV / WEBM / AVI (or audio), up to 500 MB
- Speech-to-text with automatic language detection (Whisper)
- Translation into 40 languages (MyMemory -> Google fallback chain;
  Whisper-translate fallback for English targets) — every fallback is logged,
  never silent
- Speaker gender detection from voice pitch; Auto / Male / Female voice modes
- Neural dubbing voices (Edge TTS primary — real male/female voices per
  language; gTTS automatic fallback)
- Dubbed video, subtitled video (soft subtitles), dubbed MP3, SRT/VTT
  subtitle files, transcript, and an all-in-one ZIP download
- Direct streaming downloads from the app itself (no third-party expiring
  links); video player supports seeking

## Run locally
```bash
pip install -r requirements.txt
bash run.sh            # http://localhost:8000
```

## Deploy (Render)
`render.yaml` is included — one-click Blueprint deploy, same pattern as
AI Video Studio. Optional env: `MYMEMORY_EMAIL` (raises the free translation
quota), `WHISPER_MODEL` (`base` default; `small`/`medium` = better accuracy,
slower), `MAX_UPLOAD_MB`.

## Honest limits (v1)
- Exact voice *cloning* of the original speaker in another language needs a
  paid cloning API — v1 matches gender + natural voice, not identity.
- Dub timing follows the original segment timing; very long translations are
  gently sped up (max 1.45x) to fit.
- Free translation/TTS providers have daily quotas; heavy public use needs
  paid API keys (adapters are isolated in `app/pipeline.py`).
