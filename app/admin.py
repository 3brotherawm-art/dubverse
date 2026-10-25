"""DubVerse admin panel — visitor/view counts and dub-job stats.

Routes:
  GET  /admin          login form, or the dashboard when signed in
  POST /admin/login    password check (ADMIN_PASSWORD env var)
  GET  /admin/logout   clears the admin cookie

Stats live in stats.json next to the app (views per day + unique visitor
hashes). Job stats are read from the job.json files the app already saves,
so nothing extra is tracked during dubbing. Passwords are never stored;
the admin cookie holds only a one-way hash token.
"""
import hashlib
import html
import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

_lock = threading.Lock()
_stats = None
_stats_path = None

CSS = """
:root{--bg:#0b0620;--panel:#171233;--panel2:#1f1845;--line:#2e2560;--txt:#f2efff;--mut:#a79fd0;--acc:#7c5cff;--acc2:#22d3ee;--ok:#34d399;--err:#f87171}
*{box-sizing:border-box}body{margin:0;font-family:'Segoe UI',system-ui,sans-serif;background:radial-gradient(1100px 550px at 85% -10%,#3b2a86 0%,transparent 60%),var(--bg);color:var(--txt);min-height:100vh}
.wrap{max-width:1060px;margin:0 auto;padding:26px}
h1{font-size:24px;margin:0 0 4px}h1 span{background:linear-gradient(90deg,var(--acc),var(--acc2));-webkit-background-clip:text;background-clip:text;color:transparent}
.mut{color:var(--mut);font-size:13px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin:22px 0}
.stat{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:16px;padding:18px}
.stat .num{font-size:30px;font-weight:800;margin-top:4px}
.stat .lbl{color:var(--mut);font-size:12.5px;text-transform:uppercase;letter-spacing:.6px}
.card{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:16px;padding:20px;margin-bottom:18px}
.card h2{margin:0 0 14px;font-size:16px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.5px}
.bar{height:9px;background:#120c2c;border-radius:99px;overflow:hidden;border:1px solid var(--line);min-width:90px}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--acc),var(--acc2))}
.pill{display:inline-block;padding:2px 10px;border-radius:99px;font-size:12px;border:1px solid var(--line)}
.pill.done{color:var(--ok);border-color:var(--ok)}.pill.error{color:var(--err);border-color:var(--err)}
input[type=password]{width:100%;padding:12px;border-radius:10px;background:#120c2c;color:var(--txt);border:1px solid var(--line);font-size:15px;margin:12px 0}
button{width:100%;padding:13px;border:0;border-radius:12px;background:linear-gradient(90deg,var(--acc),var(--acc2));color:#fff;font-size:15px;font-weight:700;cursor:pointer}
a{color:var(--acc2);text-decoration:none}.err{color:var(--err);font-size:13.5px;margin-top:10px}
.loginbox{max-width:380px;margin:9vh auto 0}
"""


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load():
    global _stats
    if _stats is None:
        _stats = {"views_total": 0, "views_by_day": {}, "visitors": []}
        try:
            with open(_stats_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _stats.update({k: data.get(k, _stats[k]) for k in _stats})
        except Exception:
            pass
    return _stats


def _save():
    try:
        tmp = _stats_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_stats, f)
        os.replace(tmp, _stats_path)
    except Exception:
        pass


def record_view(request):
    """Count one homepage view. Returns a new visitor id when the caller
    must set the visitor cookie, else None."""
    if _stats_path is None:
        return None
    raw = request.cookies.get("dv_vid")
    new_id = None
    if not raw:
        raw = uuid.uuid4().hex
        new_id = raw
    vid = hashlib.sha256(raw.encode()).hexdigest()[:24]
    with _lock:
        s = _load()
        s["views_total"] += 1
        day = _today()
        s["views_by_day"][day] = s["views_by_day"].get(day, 0) + 1
        if vid not in s["visitors"]:
            s["visitors"].append(vid)
            if len(s["visitors"]) > 20000:
                s["visitors"] = s["visitors"][-20000:]
        _save()
    return new_id


def _jobs_summary(jobs_dir):
    out = {"total": 0, "done": 0, "error": 0, "running": 0, "recent": []}
    try:
        entries = []
        for name in os.listdir(jobs_dir):
            p = os.path.join(jobs_dir, name, "job.json")
            if os.path.exists(p):
                entries.append((os.path.getmtime(p), p))
        entries.sort(reverse=True)
        out["total"] = len(entries)
        for mtime, p in entries:
            try:
                with open(p, encoding="utf-8") as f:
                    job = json.load(f)
            except Exception:
                continue
            status = job.get("status", "?")
            if status == "done":
                out["done"] += 1
            elif status == "error":
                out["error"] += 1
            elif status in ("running", "queued"):
                out["running"] += 1
            if len(out["recent"]) < 12:
                opts = job.get("opts") or {}
                out["recent"].append({
                    "when": datetime.fromtimestamp(mtime, timezone.utc).strftime("%d %b, %H:%M"),
                    "file": job.get("filename") or "-",
                    "pair": f"{opts.get('source_lang', 'auto')} → {opts.get('target_lang', '?')}",
                    "status": status,
                })
    except Exception:
        pass
    return out


def _token(password):
    return hashlib.sha256(("dubverse-admin::" + password).encode()).hexdigest()


def _page(title, body):
    return (f"<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
            f"<body><div class='wrap'>{body}</div></body></html>")


def register_admin(app, base_dir, jobs_dir, brand):
    global _stats_path
    _stats_path = os.path.join(base_dir, "stats.json")

    def password():
        return os.environ.get("ADMIN_PASSWORD", "")

    def authed(request):
        pw = password()
        return bool(pw) and request.cookies.get("dv_admin") == _token(pw)

    @app.get("/admin", response_class=HTMLResponse)
    def admin_home(request: Request):
        pw = password()
        if not pw:
            body = ("<div class='loginbox'><div class='card'><h2>🔒 Admin panel band hai</h2>"
                    "<p class='mut'>Admin password set nahi hai. Jahan website host hai, wahan "
                    "environment variable <b>ADMIN_PASSWORD</b> set karo, phir ye page khul jayega.</p>"
                    "<p class='mut'><a href='/'>← Website par wapas</a></p></div></div>")
            return _page(f"{brand} Admin", body)
        if not authed(request):
            body = ("<div class='loginbox'><div class='card'>"
                    f"<h2>🔒 {html.escape(brand)} — Admin</h2>"
                    "<form method='post' action='/admin/login'>"
                    "<input type='password' name='password' placeholder='Admin password' autofocus>"
                    "<button type='submit'>Login</button></form>"
                    "<p class='mut' style='margin-top:12px'><a href='/'>← Website par wapas</a></p>"
                    "</div></div>")
            return _page(f"{brand} Admin", body)
        with _lock:
            s = _load()
            views_total = s["views_total"]
            visitors = len(s["visitors"])
            by_day = dict(s["views_by_day"])
        jobs = _jobs_summary(jobs_dir)
        from . import accounts as _acc
        all_users = _acc.list_users()
        pro_count = sum(1 for u in all_users if _acc.is_pro(u))
        user_rows = ""
        for u in all_users[-30:][::-1]:
            pro = _acc.is_pro(u)
            until = ("—" if not pro else
                     ("Lifetime" if not u.get("pro_until") else
                      datetime.fromtimestamp(u["pro_until"], timezone.utc).strftime("%d %b %Y")))
            plan = "<span class='pill done'>PRO</span>" if pro else "<span class='pill'>FREE</span>"
            btns = "".join(
                f"<button name='months' value='{m}' style='width:auto;padding:5px 10px;font-size:12px;margin-right:4px'>Pro {lbl}</button>"
                for m, lbl in ((1, "1M"), (6, "6M"), (12, "1Y")))
            if pro:
                btns += "<button name='months' value='0' style='width:auto;padding:5px 10px;font-size:12px;background:#3a2b5c'>Free karo</button>"
            user_rows += (
                f"<tr><td>{html.escape(u['id'])}</td><td>{html.escape(u['name'])}</td>"
                f"<td>{html.escape(u['email'])}</td><td>{plan}</td><td>{until}</td>"
                f"<td><form method='post' action='/admin/users/set' style='display:inline'>"
                f"<input type='hidden' name='user_id' value='{html.escape(u['id'])}'>{btns}</form></td></tr>")
        if not user_rows:
            user_rows = "<tr><td colspan='6' class='mut'>Abhi tak koi user register nahi hua.</td></tr>"
        today = _today()
        days = []
        for i in range(6, -1, -1):
            d = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
            days.append((d[5:], by_day.get(d, 0)))
        max_day = max([c for _, c in days] + [1])
        day_rows = "".join(
            f"<tr><td>{d}</td><td><div class='bar'><i style='width:{int(c * 100 / max_day)}%'></i></div></td><td>{c}</td></tr>"
            for d, c in days)
        job_rows = "".join(
            f"<tr><td>{html.escape(j['when'])}</td><td>{html.escape(str(j['file']))[:38]}</td>"
            f"<td>{html.escape(j['pair'])}</td><td><span class='pill {html.escape(j['status'])}'>{html.escape(j['status'])}</span></td></tr>"
            for j in jobs["recent"]) or "<tr><td colspan='4' class='mut'>Abhi tak koi dub job nahi aayi.</td></tr>"
        done = jobs["done"]
        rate = f"{int(done * 100 / jobs['total'])}%" if jobs["total"] else "—"
        body = f"""
        <div style="display:flex;justify-content:space-between;align-items:center">
          <div><h1>{html.escape(brand)} <span>Admin</span></h1>
          <div class="mut">Website ki poori report — kitne log aaye, kitni videos dub hui</div></div>
          <a href="/admin/logout">Logout</a>
        </div>
        <div class="cards">
          <div class="stat"><div class="lbl">Total Views</div><div class="num">{views_total}</div></div>
          <div class="stat"><div class="lbl">Visitors (unique)</div><div class="num">{visitors}</div></div>
          <div class="stat"><div class="lbl">Views Today</div><div class="num">{by_day.get(today, 0)}</div></div>
          <div class="stat"><div class="lbl">Dub Jobs</div><div class="num">{jobs['total']}</div></div>
          <div class="stat"><div class="lbl">Completed</div><div class="num">{done}</div></div>
          <div class="stat"><div class="lbl">Success Rate</div><div class="num">{rate}</div></div>
          <div class="stat"><div class="lbl">Registered Users</div><div class="num">{len(all_users)}</div></div>
          <div class="stat"><div class="lbl">Pro Users</div><div class="num">{pro_count}</div></div>
        </div>
        <div class="card"><h2>👥 Users — Pro activate / deactivate</h2>
          <p class="mut">Customer payment confirm ho jaye to us ki ID ke samne wala button dabao — Pro foran active ho jayega (1M = 1 month, 6M = 6 months, 1Y = 1 year).</p>
          <table><tr><th>ID</th><th>Name</th><th>Email</th><th>Plan</th><th>Pro Until</th><th>Action</th></tr>{user_rows}</table></div>
        <div class="card"><h2>📈 Pichle 7 din ke views</h2>
          <table><tr><th>Din</th><th></th><th>Views</th></tr>{day_rows}</table></div>
        <div class="card"><h2>🎙️ Recent dub jobs</h2>
          <table><tr><th>Time (UTC)</th><th>File</th><th>Language</th><th>Status</th></tr>{job_rows}</table></div>
        <p class="mut">Note: free hosting par server restart ho to purani counting wapas zero se shuru ho sakti hai.</p>
        """
        return _page(f"{brand} Admin", body)

    @app.post("/admin/login")
    def admin_login(password_input: str = Form(..., alias="password")):
        pw = password()
        if pw and password_input == pw:
            resp = RedirectResponse("/admin", status_code=303)
            resp.set_cookie("dv_admin", _token(pw), max_age=7 * 24 * 3600,
                            httponly=True, samesite="lax")
            return resp
        body = ("<div class='loginbox'><div class='card'><h2>🔒 Admin</h2>"
                "<p class='err'>Password ghalat hai — dobara try karo.</p>"
                "<form method='post' action='/admin/login'>"
                "<input type='password' name='password' placeholder='Admin password' autofocus>"
                "<button type='submit'>Login</button></form></div></div>")
        return HTMLResponse(_page(f"{brand} Admin", body), status_code=401)

    @app.post("/admin/users/set")
    def admin_set_user(request: Request, user_id: str = Form(...),
                       months: int = Form(...)):
        if not authed(request):
            return HTMLResponse("Unauthorized", status_code=401)
        from . import accounts as _acc
        if months <= 0:
            _acc.set_free(user_id)
        else:
            _acc.set_pro(user_id, months)
        return RedirectResponse("/admin", status_code=303)

    @app.get("/admin/logout")
    def admin_logout():
        resp = RedirectResponse("/admin", status_code=303)
        resp.delete_cookie("dv_admin")
        return resp
