import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Config:
    # A fixed SECRET_KEY must be set in production (.env). The random fallback
    # only keeps local runs working; sessions reset on every restart.
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'instance' / 'sammiie.db'}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # Uploaded media (product photos, payment receipts). Use a persistent disk in production.
    MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT") or (BASE_DIR / "instance" / "media"))
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB", "12")) * 1024 * 1024

    # The admin panel lives under this path. Change it to something hard to guess.
    ADMIN_PATH = "/" + (os.environ.get("ADMIN_PATH") or "manage").strip("/")
    ADMIN_LOGIN_RATE_LIMIT = os.environ.get("ADMIN_LOGIN_RATE_LIMIT", "8 per 10 minutes")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 14
    WTF_CSRF_TIME_LIMIT = None

    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True

    # Online gateway (ZarinPal). Off until a merchant ID is set and the flow is tested.
    ZARINPAL_MERCHANT_ID = os.environ.get("ZARINPAL_MERCHANT_ID", "")
    ZARINPAL_SANDBOX = _bool("ZARINPAL_SANDBOX", True)
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

    # Unpaid card-to-card orders release their stock after this many hours.
    ORDER_HOLD_HOURS = int(os.environ.get("ORDER_HOLD_HOURS", "48"))


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
