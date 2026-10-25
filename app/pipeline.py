"""DubVerse processing pipeline.

upload -> extract audio -> Whisper transcription -> speaker-gender detection
-> segment translation -> neural TTS dubbing (gender-matched) -> muxed video
+ subtitle files + ZIP.

Design rules (from the owner):
- The dubbing voice must match the speaker: male speaker -> male voice,
  female speaker -> female voice (auto-detected from pitch, user can override).
- No silent fake results: every fallback (translation provider, TTS provider)
  is recorded in the job log and surfaced to the user.
"""
import asyncio
import json
import math
import os
import re
import subprocess
import time
import wave
import zipfile

import numpy as np
import requests

from .languages import LANGUAGES

SR = 24000  # dub timeline sample rate
_MODELS_DIR = os.path.expanduser("~/workspace/.venvs/models")


def _model_path():
    # 'small' is the default: the 'base' model garbles Urdu/Hindi speech,
    # which then poisons the translation. Small is far more accurate.
    env = os.environ.get("WHISPER_MODEL")
    if env:
        return env
    for name in ("faster-whisper-small", "faster-whisper-base"):
        path = os.path.join(_MODELS_DIR, name)
        if os.path.isdir(path):
            return path
    return "small"


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd[:3])}... {p.stderr[-400:]}")
    return p


def probe_duration(path):
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", path], capture_output=True, text=True)
    try:
        return float(json.loads(p.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def probe_has_video(path):
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_type", "-of", "json", path],
        capture_output=True, text=True)
    try:
        return bool(json.loads(p.stdout).get("streams"))
    except Exception:
        return False


def probe_height(path):
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=height", "-of", "json", path],
        capture_output=True, text=True)
    try:
        return int(json.loads(p.stdout)["streams"][0]["height"])
    except Exception:
        return 0


def _video_args(max_height, src_height):
    """Free plan caps output at max_height (e.g. 1080p); Pro (None) keeps the
    original stream untouched via stream copy."""
    if max_height and src_height and src_height > max_height:
        return ["-vf", f"scale=-2:{max_height}", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "19"]
    return ["-c:v", "copy"]


def decode_audio(path, sr=SR):
    """Decode any media file to float32 mono samples via PyAV."""
    import av
    from av.audio.resampler import AudioResampler
    container = av.open(path)
    stream = next((s for s in container.streams if s.type == "audio"), None)
    if stream is None:
        raise RuntimeError("file me audio stream nahi mila")
    resampler = AudioResampler(format="s16", layout="mono", rate=sr)
    chunks = []
    for frame in container.decode(stream):
        for out in resampler.resample(frame):
            chunks.append(out.to_ndarray().reshape(-1))
    for out in resampler.resample(None):
        chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def write_wav(path, samples, sr=SR):
    data = np.clip(samples, -1.0, 1.0)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((data * 32767).astype(np.int16).tobytes())


# ---------------------------------------------------------------- transcription
def transcribe(audio_path, source_lang):
    from faster_whisper import WhisperModel
    model = WhisperModel(_model_path(), device="cpu", compute_type="int8")
    kwargs = {"beam_size": 5, "vad_filter": True}
    if source_lang and source_lang != "auto":
        kwargs["language"] = source_lang
    # NOTE: pass a decoded numpy array, not a path — this PyAV build rejects
    # the metadata_errors kwarg faster-whisper uses when opening files itself.
    samples = decode_audio(audio_path, 16000)
    segments, info = model.transcribe(samples, **kwargs)
    segs = [
        {"start": float(s.start), "end": float(s.end), "text": s.text.strip()}
        for s in segments if s.text.strip()
    ]
    return segs, (info.language or source_lang or "en")


def transcribe_english(audio_path):
    """Whisper's built-in translate task (any language -> English)."""
    from faster_whisper import WhisperModel
    model = WhisperModel(_model_path(), device="cpu", compute_type="int8")
    samples = decode_audio(audio_path, 16000)
    segments, _ = model.transcribe(samples, task="translate", beam_size=5,
                                   vad_filter=True)
    return [
        {"start": float(s.start), "end": float(s.end), "text": s.text.strip()}
        for s in segments if s.text.strip()
    ]


# ---------------------------------------------------------------- gender detect
def _f0_autocorr(x, sr):
    if len(x) < int(sr * 0.12):
        return None
    x = x - np.mean(x)
    if np.max(np.abs(x)) < 0.02:
        return None
    corr = np.correlate(x, x, mode="full")[len(x) - 1:]
    min_lag, max_lag = int(sr / 400), int(sr / 55)  # 55-400 Hz
    if max_lag >= len(corr):
        return None
    window = corr[min_lag:max_lag]
    peak_val = float(np.max(window))
    if peak_val <= 0.25 * corr[0]:
        return None
    # Octave guard: raw argmax often lands on double the true period
    # (half the true pitch). Take the smallest lag that is nearly as
    # strong as the peak instead — that is the true fundamental.
    thresh = 0.92 * peak_val
    peak = min_lag + int(np.argmax(window >= thresh))
    return sr / peak


def detect_gender(samples, sr, segments):
    f0s = []
    for seg in segments:
        a = int(seg["start"] * sr)
        b = min(len(samples), int(seg["end"] * sr))
        if b - a < int(sr * 0.15):
            continue
        chunk = samples[a:b]
        mid = chunk[: int(sr * 1.5)]
        f0 = _f0_autocorr(mid.astype(np.float64), sr)
        if f0:
            f0s.append(f0)
    if not f0s:
        return "unknown", None
    median = float(np.median(f0s))
    return ("male" if median < 168 else "female"), round(median, 1)


# ---------------------------------------------------------------- translation
def _chunks(text, limit=440):
    if len(text) <= limit:
        return [text]
    parts = re.split(r"(?<=[.!?।])\s+", text)
    out, cur = [], ""
    for p in parts:
        if len(cur) + len(p) + 1 <= limit:
            cur = (cur + " " + p).strip()
        else:
            if cur:
                out.append(cur)
            while len(p) > limit:
                out.append(p[:limit])
                p = p[limit:]
            cur = p
    if cur:
        out.append(cur)
    return out


def _mymemory(text, src, tgt):
    email = os.environ.get("MYMEMORY_EMAIL", "")
    done = []
    for chunk in _chunks(text):
        params = {"q": chunk, "langpair": f"{src}|{tgt}"}
        if email:
            params["de"] = email
        r = requests.get("https://api.mymemory.translated.net/get",
                         params=params, timeout=25)
        data = r.json()
        status = str(data.get("responseStatus", ""))
        translated = (data.get("responseData") or {}).get("translatedText", "")
        if status != "200" or not translated or "QUERY LENGTH LIMIT" in translated \
                or "INVALID" in translated.upper():
            raise RuntimeError(f"mymemory status {status}")
        done.append(translated)
        time.sleep(0.12)
    return " ".join(done)


def _google(text, src, tgt):
    from deep_translator import GoogleTranslator
    done = []
    for chunk in _chunks(text, 4500):
        done.append(GoogleTranslator(source=src or "auto", target=tgt)
                    .translate(chunk))
        time.sleep(0.12)
    return " ".join(done)


def translate_text(text, src, tgt):
    """Returns (translated_text, provider_name). Raises if all providers fail."""
    if src == tgt:
        return text, "same-language"
    errors = []
    for name, fn in (("mymemory", _mymemory), ("google", _google)):
        try:
            out = fn(text, src, tgt)
            if out and out.strip():
                return out.strip(), name
        except Exception as e:  # provider down / rate-limited -> try next
            errors.append(f"{name}: {e}")
    raise RuntimeError(" | ".join(errors))


# ---------------------------------------------------------------- TTS dubbing
def _edge_tts(text, voice, out_path):
    import edge_tts

    async def _save():
        await edge_tts.Communicate(text, voice).save(out_path)

    asyncio.run(_save())


def _gtts(text, lang_code, out_path):
    from gtts import gTTS
    gTTS(text=text, lang=lang_code).save(out_path)


def synth_segment(text, lang_info, gender, out_path, log):
    """Try Edge neural voice (gendered) first, then gTTS. Returns engine name."""
    edge = lang_info.get("edge")
    if edge:
        voice = edge[1] if gender == "male" else edge[2]
        try:
            _edge_tts(text, voice, out_path)
            if os.path.getsize(out_path) > 800:
                return f"edge:{voice}"
        except Exception as e:
            log(f"Edge TTS fail ({voice}): {str(e)[:120]} — fallback try kar raha hoon")
    if lang_info.get("gtts"):
        _gtts(text, lang_info["gtts"], out_path)
        return "gtts"
    raise RuntimeError("is language ke liye koi TTS voice available nahi")


# ---------------------------------------------------------------- subtitles
def _ts(seconds, vtt=False):
    ms = int(round((seconds - int(seconds)) * 1000))
    s = int(seconds) % 60
    m = (int(seconds) // 60) % 60
    h = int(seconds) // 3600
    sep = "." if vtt else ","
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def write_srt(path, segments):
    with open(path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            f.write(f"{i}\n{_ts(seg['start'])} --> {_ts(seg['end'])}\n"
                    f"{seg['text']}\n\n")


def write_vtt(path, segments):
    with open(path, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for seg in segments:
            f.write(f"{_ts(seg['start'], True)} --> {_ts(seg['end'], True)}\n"
                    f"{seg['text']}\n\n")


# ---------------------------------------------------------------- main pipeline
def process_job(job_dir, input_path, opts, log, progress):
    """opts: source_lang, target_lang, voice_mode(auto|male|female),
    make_dub, make_subs, bg_original (bool), bg_volume (0-0.4)."""
    target = opts["target_lang"]
    lang_info = LANGUAGES[target]
    tgt_code = lang_info["google"]
    outputs = {}
    meta = {}

    progress(8, "Audio extract ho raha hai")
    audio_wav = os.path.join(job_dir, "audio.wav")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", input_path,
         "-vn", "-ac", "1", "-ar", "16000", audio_wav])
    total_dur = probe_duration(input_path)
    has_video = probe_has_video(input_path)
    src_height = probe_height(input_path) if has_video else 0
    max_height = opts.get("max_height")
    meta["duration_sec"] = round(total_dur, 1)
    meta["input_height"] = src_height
    meta["quality"] = ("full (Pro)" if not max_height else
                        (f"max {max_height}p (Free)" if src_height > (max_height or 0)
                         else "original"))

    progress(18, "Whisper se transcription ho rahi hai")
    segments, detected = transcribe(audio_wav, opts["source_lang"])
    if not segments:
        raise RuntimeError("video me koi speech detect nahi hui")
    src_code = detected
    # translation providers want full codes for a few languages
    src_for_mt = {"zh": "zh-CN"}.get(src_code, src_code)
    meta["detected_language"] = src_code
    meta["segments"] = len(segments)

    progress(34, "Speaker ki awaz check ho rahi hai (male/female)")
    samples16 = decode_audio(audio_wav, 16000)
    gender, f0 = detect_gender(samples16, 16000, segments)
    meta["speaker_gender"] = gender
    meta["speaker_f0_hz"] = f0
    voice_gender = opts["voice_mode"] if opts["voice_mode"] in ("male", "female") \
        else (gender if gender in ("male", "female") else "female")
    meta["voice_gender"] = voice_gender

    progress(44, f"Translation ho rahi hai ({src_code} -> {tgt_code})")
    translated, providers = [], set()
    whisper_en = None
    for seg in segments:
        try:
            text, provider = translate_text(seg["text"], src_for_mt, tgt_code)
            providers.add(provider)
        except Exception as e:
            log(f"segment translation fail: {str(e)[:140]}")
            if tgt_code == "en" and src_code != "en":
                if whisper_en is None:
                    whisper_en = transcribe_english(audio_wav)
                text = _nearest_text(whisper_en, seg)
                providers.add("whisper-translate")
            else:
                text = seg["text"]
                providers.add("passthrough-original")
        translated.append({"start": seg["start"], "end": seg["end"], "text": text})
    meta["translation_providers"] = sorted(providers)
    if "passthrough-original" in providers:
        log("WARNING: kuch segments translate nahi ho sake — original text rakha gaya hai")

    write_srt(os.path.join(job_dir, "subtitles_original.srt"), segments)
    write_vtt(os.path.join(job_dir, "subtitles_original.vtt"), segments)
    write_srt(os.path.join(job_dir, "subtitles_translated.srt"), translated)
    write_vtt(os.path.join(job_dir, "subtitles_translated.vtt"), translated)
    outputs["subtitles_translated.srt"] = "Translated subtitles (SRT)"
    outputs["subtitles_original.srt"] = "Original subtitles (SRT)"
    with open(os.path.join(job_dir, "transcript.txt"), "w", encoding="utf-8") as f:
        for o, t in zip(segments, translated):
            f.write(f"[{o['start']:.1f}s] {o['text']}\n        -> {t['text']}\n")
    outputs["transcript.txt"] = "Transcript + translation"

    if opts["make_subs"] and has_video:
        progress(58, "Subtitled video ban raha hai")
        subbed = os.path.join(job_dir, "video_subtitled.mp4")
        capped = bool(max_height and src_height > max_height)
        sub_cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", input_path,
                   "-i", os.path.join(job_dir, "subtitles_translated.srt"),
                   "-map", "0", "-map", "1",
                   "-c:s", "mov_text",
                   "-metadata:s:s:0", f"language={tgt_code[:3]}"]
        if capped:
            sub_cmd += ["-vf", f"scale=-2:{max_height}", "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "19", "-c:a", "copy"]
        else:
            sub_cmd += ["-c", "copy"]
        sub_cmd.append(subbed)
        p = subprocess.run(sub_cmd, capture_output=True, text=True)
        if p.returncode == 0:
            outputs["video_subtitled.mp4"] = "Video with translated subtitles"
        else:
            log("subtitled video mux fail — sirf SRT files milengi")

    if opts["make_dub"]:
        progress(64, f"Dubbing voice generate ho rahi hai ({voice_gender})")
        canvas_len = int((total_dur + 2.0) * SR)
        canvas = np.zeros(canvas_len, dtype=np.float32)
        engines = set()
        for i, seg in enumerate(translated):
            if not seg["text"]:
                continue
            seg_mp3 = os.path.join(job_dir, f"seg_{i:03d}.mp3")
            engine = synth_segment(seg["text"], lang_info, voice_gender, seg_mp3, log)
            engines.add(engine.split(":")[0])
            nxt = translated[i + 1]["start"] if i + 1 < len(translated) else total_dur + 1.5
            window = max(nxt - seg["start"], seg["end"] - seg["start"], 0.8)
            dur = probe_duration(seg_mp3)
            fit_path = seg_mp3
            if dur > window * 1.03 and dur > 0:
                factor = min(dur / window, 1.45)
                fit_path = os.path.join(job_dir, f"seg_{i:03d}_fit.wav")
                run(["ffmpeg", "-y", "-loglevel", "error", "-i", seg_mp3,
                     "-filter:a", f"atempo={factor:.3f}", fit_path])
            samples = decode_audio(fit_path, SR)
            pos = int(seg["start"] * SR)
            end = min(canvas_len, pos + len(samples))
            if end > pos:
                canvas[pos:end] += samples[: end - pos]
            progress(64 + int(20 * (i + 1) / len(translated)),
                     f"Dubbing {i + 1}/{len(translated)} segments")
        meta["tts_engines"] = sorted(engines)
        if opts.get("bg_original"):
            orig = decode_audio(audio_wav, SR)
            n = min(len(orig), canvas_len)
            canvas[:n] += orig[:n] * float(opts.get("bg_volume", 0.15))
        peak = float(np.max(np.abs(canvas))) if canvas.size else 0.0
        if peak > 0.92:
            canvas *= 0.92 / peak
        dubbed_wav = os.path.join(job_dir, "dubbed_audio.wav")
        write_wav(dubbed_wav, canvas)
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", dubbed_wav,
             os.path.join(job_dir, "dubbed_audio.mp3")])
        outputs["dubbed_audio.mp3"] = "Dubbed audio only (MP3)"

        if has_video:
            progress(88, "Dubbed video mux ho raha hai")
            dubbed_mp4 = os.path.join(job_dir, "video_dubbed.mp4")
            vargs = _video_args(max_height, src_height)
            capped = "-vf" in vargs
            p = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", input_path,
                 "-i", dubbed_wav, "-map", "0:v:0", "-map", "1:a:0",
                 *vargs, "-c:a", "aac", "-b:a", "160k", dubbed_mp4],
                capture_output=True, text=True)
            if p.returncode != 0 and not capped:
                # codec not mp4-friendly -> re-encode video (keeping any cap)
                fb = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
                if max_height and src_height > max_height:
                    fb = ["-vf", f"scale=-2:{max_height}"] + fb
                run(["ffmpeg", "-y", "-loglevel", "error", "-i", input_path,
                     "-i", dubbed_wav, "-map", "0:v:0", "-map", "1:a:0",
                     *fb, "-c:a", "aac", "-b:a", "160k", dubbed_mp4])
            outputs["video_dubbed.mp4"] = "Dubbed video (MP4)"

    progress(96, "Download package tayyar ho raha hai")
    zip_path = os.path.join(job_dir, "dubverse_output.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for name in list(outputs.keys()) + ["subtitles_translated.vtt"]:
            full = os.path.join(job_dir, name)
            if os.path.exists(full):
                z.write(full, arcname=name)
    outputs["dubverse_output.zip"] = "All files (ZIP)"
    return outputs, meta


def _nearest_text(segs, target):
    best, best_d = "", 1e9
    for s in segs:
        d = abs(s["start"] - target["start"])
        if d < best_d:
            best, best_d = s["text"], d
    return best
