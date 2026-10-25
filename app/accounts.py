"""DubVerse user accounts + Pro plans.

Storage: users.json next to the app. Passwords are stored only as salted
SHA-256 hashes. The session cookie holds a one-way token derived from the
user id + password hash, so it never contains the password itself.

Plans (owner's pricing, PKR):
  Free — video quality up to 1080p
  Pro  — full original quality (4K / 8K / 16K sources stay untouched)
         1 month Rs 300, 6 months Rs 1200 (was 1800), 1 year Rs 2000 (was 3600)
Payment is manual: the customer pays via Easypaisa and sends the screenshot
on WhatsApp; the owner then activates Pro from the admin panel (or asks
Muse, who uses the same panel).
"""
import hashlib
import json
import os
import threading
import time
import uuid

_lock = threading.Lock()
_users = None
_path = None

PLANS = [
    {"key": "monthly", "label": "1 Month", "months": 1, "price": 300, "mrp": 300},
    {"key": "halfyear", "label": "6 Months", "months": 6, "price": 1200, "mrp": 1800},
    {"key": "yearly", "label": "1 Year", "months": 12, "price": 2000, "mrp": 3600},
]
FREE_MAX_HEIGHT = 1080


def whatsapp_number():
    # Owner's business number (also his Easypaisa number): 0303-9929254
    return os.environ.get("WHATSAPP_NUMBER", "923039929254")


def easypaisa_number():
    return os.environ.get("EASYPAISA_NUMBER", "0303-9929254")


def init(base_dir):
    global _path
    _path = os.path.join(base_dir, "users.json")
    _load()


def _load():
    global _users
    if _users is None:
        _users = []
        try:
            with open(_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                _users = data
        except Exception:
            pass
    return _users


def _save():
    try:
        tmp = _path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_users, f, ensure_ascii=False)
        os.replace(tmp, _path)
    except Exception:
        pass


def _hash(password, salt):
    return hashlib.sha256((salt + "::" + password).encode()).hexdigest()


def register(name, email, password):
    email = (email or "").strip().lower()
    name = (name or "").strip()
    if not name or "@" not in email or len(password or "") < 6:
        return None, "Name, sahi email, aur kam az kam 6 characters ka password chahiye"
    with _lock:
        users = _load()
        if any(u["email"] == email for u in users):
            return None, "Is email se account pehle se bana hua hai — Login karo"
        salt = uuid.uuid4().hex[:16]
        user = {
            "id": "DV-" + uuid.uuid4().hex[:6].upper(),
            "name": name,
            "email": email,
            "salt": salt,
            "pass_hash": _hash(password, salt),
            "plan": "free",
            "pro_until": None,
            "created": int(time.time()),
        }
        users.append(user)
        _save()
        return user, None


def register_oauth(name, email):
    """Find the account for this email or create one for Google sign-in.
    Google accounts get a random unusable password — they always log in
    via Google. If the email already registered with a password, the same
    account is linked (no duplicate)."""
    email = (email or "").strip().lower()
    name = (name or "").strip() or email.split("@")[0]
    with _lock:
        users = _load()
        for u in users:
            if u["email"] == email:
                return u
        salt = uuid.uuid4().hex[:16]
        user = {
            "id": "DV-" + uuid.uuid4().hex[:6].upper(),
            "name": name,
            "email": email,
            "salt": salt,
            "pass_hash": _hash(uuid.uuid4().hex, salt),
            "plan": "free",
            "pro_until": None,
            "created": int(time.time()),
            "provider": "google",
        }
        users.append(user)
        _save()
        return user


def verify(email, password):
    email = (email or "").strip().lower()
    with _lock:
        for u in _load():
            if u["email"] == email and u["pass_hash"] == _hash(password or "", u["salt"]):
                return u
    return None


def session_token(user):
    return hashlib.sha256(
        ("dubverse-session::" + user["id"] + "::" + user["pass_hash"]).encode()
    ).hexdigest()


def user_by_token(request):
    tok = request.cookies.get("dv_user")
    if not tok:
        return None
    with _lock:
        for u in _load():
            if session_token(u) == tok:
                return u
    return None


def is_pro(user):
    if not user or user.get("plan") != "pro":
        return False
    until = user.get("pro_until")
    return until is None or until > time.time()


def public_user(user):
    if not user:
        return None
    pro = is_pro(user)
    return {
        "id": user["id"], "name": user["name"], "email": user["email"],
        "plan": "pro" if pro else "free",
        "pro_until": user.get("pro_until") if pro else None,
    }


def list_users():
    with _lock:
        return [dict(u) for u in _load()]


def set_pro(user_id, months):
    """Activate/extend Pro for a user. months=None means lifetime (not used
    by the current plans, kept for manual fixes). Returns the user or None."""
    with _lock:
        for u in _load():
            if u["id"] == user_id:
                now = time.time()
                base = u["pro_until"] if (u.get("pro_until") and u["pro_until"] > now) else now
                u["plan"] = "pro"
                u["pro_until"] = None if months is None else int(base + months * 30 * 24 * 3600)
                _save()
                return u
    return None


def set_free(user_id):
    with _lock:
        for u in _load():
            if u["id"] == user_id:
                u["plan"] = "free"
                u["pro_until"] = None
                _save()
                return u
    return None
