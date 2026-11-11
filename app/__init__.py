from __future__ import annotations

import os
import secrets

from flask import Flask, g, render_template, request, url_for

from . import orders, settings
from .config import Config
from .extensions import csrf, db, limiter
from .utils import fa, group_digits, jdate, money


def create_app(config_object=None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object or Config)
    os.makedirs(app.instance_path, exist_ok=True)
    if os.environ.get("TRUST_PROXY", "0") == "1":
        # Behind ParsPack / nginx: trust one proxy hop for the client IP and https scheme.
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    if app.config.get("RATELIMIT_ENABLED") is False:
        limiter.enabled = False

    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    from .shop import shop_bp
    from .admin.views import admin_bp
    app.register_blueprint(shop_bp)
    app.register_blueprint(admin_bp, url_prefix=app.config["ADMIN_PATH"])

    from .cli import register_cli
    register_cli(app)

    with app.app_context():
        db.create_all()

    app.jinja_env.filters.update(fa=fa, money=money, jdate=jdate, card=lambda v: fa(group_digits(v)))

    def media_url(rel: str | None) -> str:
        if not rel:
            return url_for("static", filename="img/placeholder.svg")
        return url_for("shop.media", name=rel.removeprefix("products/"))

    app.jinja_env.globals["media_url"] = media_url

    @app.context_processor
    def inject():
        return {"S": settings.get_all(), "cart_count": orders.cart_count(),
                "csp_nonce": g.get("csp_nonce", ""), "admin_path": app.config["ADMIN_PATH"]}

    @app.before_request
    def nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.after_request
    def security_headers(response):
        n = g.get("csp_nonce", "")
        response.headers.setdefault("Content-Security-Policy",
                                    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                                    f"script-src 'self' 'nonce-{n}'; font-src 'self'; frame-ancestors 'none'; "
                                    "base-uri 'self'; form-action 'self' https://*.zarinpal.com")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    @app.errorhandler(404)
    def not_found(_):
        return render_template("shop/error.html", code=404, title="این صفحه پیدا نشد",
                               text="شاید جابه‌جا شده یا هیچ‌وقت بافته نشده!"), 404

    @app.errorhandler(413)
    def too_large(_):
        return render_template("shop/error.html", code=413, title="فایل خیلی بزرگ است",
                               text="حجم تصویر را کمتر کن و دوباره بفرست."), 413

    @app.errorhandler(429)
    def too_many(_):
        return render_template("shop/error.html", code=429, title="کمی صبر کن",
                               text="درخواست‌ها زیاد بود؛ چند دقیقه دیگر دوباره امتحان کن."), 429

    @app.errorhandler(500)
    def server_error(_):
        db.session.rollback()
        return render_template("shop/error.html", code=500, title="مشکلی پیش آمد",
                               text="خطا ثبت شد. لطفاً دوباره امتحان کن."), 500

    return app
