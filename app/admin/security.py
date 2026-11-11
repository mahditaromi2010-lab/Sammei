"""Admin sessions, optional two-factor codes (TOTP, RFC 6238) and the audit log.
Adapted from SentinelWeb's admin panel."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import timedelta
from functools import wraps
from urllib.parse import quote

from flask import g, redirect, request, session, url_for

from ..extensions import db
from ..models import AdminUser, AuditLog
from ..utils import utcnow

TOTP_PERIOD = 30
MAX_FAILED = 6
LOCK_MINUTES = 15
IDLE_MINUTES = 120


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return str(code).zfill(6)


def totp_now(secret: str, at: float | None = None) -> str:
    return _hotp(secret, int((time.time() if at is None else at) // TOTP_PERIOD))


def verify_totp(user: AdminUser, code: str, secret: str | None = None) -> bool:
    secret = secret or user.totp_secret
    code = (code or "").strip().replace(" ", "")
    if not secret or len(code) != 6 or not code.isdigit():
        return False
    step = int(time.time() // TOTP_PERIOD)
    for candidate in (step - 1, step, step + 1):
        if user.totp_last_step is not None and candidate <= user.totp_last_step:
            continue
        if hmac.compare_digest(_hotp(secret, candidate), code):
            user.totp_last_step = candidate
            return True
    return False


def provisioning_uri(user: AdminUser, secret: str) -> str:
    issuer = "Sammiie Admin"
    return f"otpauth://totp/{quote(issuer)}:{quote(user.username)}?secret={secret}&issuer={quote(issuer)}"


def client_ip() -> str:
    return (request.remote_addr or "")[:64]


def is_locked(user: AdminUser) -> bool:
    return bool(user.locked_until and user.locked_until > utcnow())


def register_failure(user: AdminUser) -> None:
    user.failed_logins = (user.failed_logins or 0) + 1
    if user.failed_logins >= MAX_FAILED:
        user.locked_until = utcnow() + timedelta(minutes=LOCK_MINUTES)
        user.failed_logins = 0
    db.session.commit()


def start_session(user: AdminUser) -> None:
    session.pop("admin", None)
    session["admin"] = {"id": user.id, "v": user.session_version, "seen": int(time.time())}
    session.permanent = True
    user.failed_logins = 0
    user.locked_until = None
    user.last_login = utcnow()
    db.session.commit()


def end_session() -> None:
    session.pop("admin", None)


def current_admin() -> AdminUser | None:
    if "admin_user" in g:
        return g.admin_user
    data = session.get("admin") or {}
    user = db.session.get(AdminUser, data.get("id")) if data.get("id") else None
    now = int(time.time())
    if user is None or not user.is_active or data.get("v") != user.session_version \
            or now - int(data.get("seen", 0)) > IDLE_MINUTES * 60:
        if data:
            session.pop("admin", None)
        user = None
    else:
        data["seen"] = now
        session["admin"] = data
    g.admin_user = user
    return user


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if current_admin() is None:
            return redirect(url_for("admin.login", next=request.full_path if request.method == "GET" else None))
        return view(*args, **kwargs)
    return wrapper


def audit(action: str, target: str = "", detail: str = "", admin: str | None = None) -> None:
    user = current_admin()
    db.session.add(AuditLog(admin=admin or (user.username if user else "-"), action=action,
                            target=str(target)[:120], detail=str(detail)[:500], ip=client_ip()))
    db.session.commit()
