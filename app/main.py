"""DubVerse — video translator & AI dubbing studio (FastAPI)."""
import json
import os
import shutil
import threading
import uuid

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import accounts
from .admin import record_view, register_admin
from .languages import LANGUAGES, language_list
from .pipeline import process_job

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOBS = os.path.join(BASE, "jobs")
STATIC = os.path.join(BASE, "app", "static")
BRAND = os.environ.get("BRAND_NAME", "DubVerse")
MAX_MB = int(os.environ.get("MAX_UPLOAD_MB", "500"))
ALLOWED = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".mp3", ".wav", ".m4a", ".aac"}

os.makedirs(JOBS, exist_ok=True)
app = FastAPI(title=BRAND)
accounts.init(BASE)
register_admin(app, BASE, JOBS, BRAND)
_jobs = {}
_lock = threading.Lock()


def _save(job):
    with open(os.path.join(JOBS, job["id"], "job.json"), "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=1)


def _run_job(job_id, job_dir, input_path, opts):
    job = _jobs[job_id]
    logs = job["logs"]

    def log(msg):
        logs.append(str(msg))

    def progress(pct, step):
        job["progress"] = pct
        job["step"] = step
        _save(job)

    try:
        job["status"] = "running"
        progress(3, "Job start")
        outputs, meta = process_job(job_dir, input_path, opts, log, progress)
        job["outputs"] = outputs
        job["meta"] = meta
        job["status"] = "done"
        progress(100, "Complete")
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)[:600]
        job["step"] = "Fail ho gaya"
        _save(job)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as f:
        page = f.read().replace("__BRAND__", BRAND)
    resp = HTMLResponse(page)
    new_visitor = record_view(request)
    if new_visitor:
        resp.set_cookie("dv_vid", new_visitor, max_age=365 * 24 * 3600,
                        httponly=True, samesite="lax")
    return resp


@app.get("/api/config")
def config():
    return {"brand": BRAND, "max_upload_mb": MAX_MB, "languages": language_list(),
            "whatsapp": accounts.whatsapp_number(),
            "easypaisa": accounts.easypaisa_number(),
            "plans": accounts.PLANS,
            "free_max_height": accounts.FREE_MAX_HEIGHT}


@app.post("/api/register")
def api_register(name: str = Form(...), email: str = Form(...),
                 password: str = Form(...)):
    user, err = accounts.register(name, email, password)
    if err:
        raise HTTPException(400, err)
    resp = JSONResponse({"user": accounts.public_user(user)})
    resp.set_cookie("dv_user", accounts.session_token(user),
                    max_age=30 * 24 * 3600, httponly=True, samesite="lax")
    return resp


@app.post("/api/login")
def api_login(email: str = Form(...), password: str = Form(...)):
    user = accounts.verify(email, password)
    if not user:
        raise HTTPException(401, "Email ya password ghalat hai")
    resp = JSONResponse({"user": accounts.public_user(user)})
    resp.set_cookie("dv_user", accounts.session_token(user),
                    max_age=30 * 24 * 3600, httponly=True, samesite="lax")
    return resp


@app.post("/api/logout")
def api_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("dv_user")
    return resp


@app.get("/api/me")
def api_me(request: Request):
    return {"user": accounts.public_user(accounts.user_by_token(request))}


@app.post("/api/jobs")
def create_job(
    request: Request,
    file: UploadFile = File(...),
    source_lang: str = Form("auto"),
    target_lang: str = Form("ur"),
    voice_mode: str = Form("auto"),
    make_dub: bool = Form(True),
    make_subs: bool = Form(True),
    bg_original: bool = Form(False),
    bg_volume: float = Form(0.15),
):
    if target_lang not in LANGUAGES:
        raise HTTPException(400, "target language supported nahi hai")
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED:
        raise HTTPException(400, f"file type allowed nahi: {ext}")
    job_id = uuid.uuid4().hex[:12]
    job_dir = os.path.join(JOBS, job_id)
    os.makedirs(job_dir, exist_ok=True)
    input_path = os.path.join(job_dir, "input" + ext)
    with open(input_path, "wb") as out:
        shutil.copyfileobj(file.file, out, length=1024 * 1024)
    size_mb = os.path.getsize(input_path) / (1024 * 1024)
    if size_mb > MAX_MB:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(400, f"file bohat bari hai ({size_mb:.0f} MB > {MAX_MB} MB)")
    user = accounts.user_by_token(request)
    pro = accounts.is_pro(user)
    opts = {
        "source_lang": source_lang, "target_lang": target_lang,
        "voice_mode": voice_mode, "make_dub": make_dub, "make_subs": make_subs,
        "bg_original": bg_original, "bg_volume": bg_volume,
        # Free plan: output capped at 1080p. Pro: full original quality.
        "max_height": None if pro else accounts.FREE_MAX_HEIGHT,
    }
    job = {"id": job_id, "status": "queued", "progress": 0, "step": "Queue me hai",
           "logs": [], "outputs": {}, "meta": {}, "error": None,
           "filename": file.filename, "opts": opts,
           "user": (user or {}).get("id"), "plan": "pro" if pro else "free"}
    with _lock:
        _jobs[job_id] = job
    _save(job)
    threading.Thread(target=_run_job, args=(job_id, job_dir, input_path, opts),
                     daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        meta_path = os.path.join(JOBS, job_id, "job.json")
        if os.path.exists(meta_path):
            with open(meta_path, encoding="utf-8") as f:
                job = json.load(f)
        else:
            raise HTTPException(404, "job nahi mila")
    return JSONResponse(job)


@app.get("/api/jobs/{job_id}/files/{name}")
def get_file(job_id: str, name: str, download: int = 0):
    if "/" in name or ".." in name:
        raise HTTPException(400, "bad name")
    path = os.path.join(JOBS, job_id, name)
    if not os.path.exists(path):
        raise HTTPException(404, "file nahi mili")
    if download:
        return FileResponse(path, filename=name)
    media = {".mp4": "video/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav",
             ".srt": "text/plain", ".vtt": "text/vtt", ".txt": "text/plain",
             ".zip": "application/zip"}
    return FileResponse(path, media_type=media.get(os.path.splitext(name)[1], None))
