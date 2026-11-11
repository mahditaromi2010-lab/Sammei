"""Admin panel: dashboard, products, categories, orders & payments, coupons, messages, settings."""
from __future__ import annotations

import csv
import io
from datetime import timedelta

from flask import (Blueprint, Response, abort, current_app, flash, redirect, render_template, request,
                   send_from_directory, url_for)
from sqlalchemy import func, or_
from werkzeug.security import check_password_hash, generate_password_hash

from .. import orders, settings
from ..extensions import db, limiter
from ..media import ImageError, delete_media, media_root, save_product_image
from ..models import (ORDER_STATUSES, AdminUser, AuditLog, Category, Coupon, Message, Order, OrderItem,
                      Payment, Product, ProductImage, Subscriber)
from ..settings import DEFAULTS
from ..utils import en_digits, parse_int, slugify, utcnow, valid_card
from .security import (admin_required, audit, client_ip, current_admin, end_session, is_locked,
                       new_totp_secret, provisioning_uri, register_failure, start_session, verify_totp)

admin_bp = Blueprint("admin", __name__, template_folder="../templates/admin")
_DUMMY_HASH = generate_password_hash("not-a-real-password")


@admin_bp.context_processor
def nav_counts():
    if current_admin() is None:
        return {}
    return {"nav_review": Order.query.filter_by(status="payment_review").count(),
            "nav_msgs": Message.query.filter_by(is_read=False).count()}


@admin_bp.after_request
def no_store(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


# ------------------------------------------------------------------ auth

@admin_bp.route("/login", methods=["GET", "POST"])
@limiter.limit(lambda: current_app.config["ADMIN_LOGIN_RATE_LIMIT"], methods=["POST"])
def login():
    if current_admin():
        return redirect(url_for("admin.dashboard"))
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()[:64]
        password = request.form.get("password") or ""
        code = request.form.get("code") or ""
        user = AdminUser.query.filter(func.lower(AdminUser.username) == username.lower()).first() if username else None
        if user is None:
            check_password_hash(_DUMMY_HASH, password)  # same timing as a real check
            error = "نام کاربری، رمز یا کد اشتباه است."
        elif not user.is_active or is_locked(user):
            error = "این حساب موقتاً قفل است. چند دقیقه دیگر دوباره امتحان کن."
        elif not user.check_password(password) or (user.totp_secret and not verify_totp(user, code)):
            register_failure(user)
            audit("login_failed", user.username, admin=user.username)
            error = "نام کاربری، رمز یا کد اشتباه است."
        else:
            start_session(user)
            audit("login", user.username)
            nxt = request.args.get("next") or ""
            prefix = current_app.config["ADMIN_PATH"]
            return redirect(nxt if nxt.startswith(prefix + "/") and "//" not in nxt else url_for("admin.dashboard"))
    return render_template("admin/login.html", error=error)


@admin_bp.route("/logout", methods=["POST"])
def logout():
    if current_admin():
        audit("logout")
    end_session()
    return redirect(url_for("admin.login"))


# ------------------------------------------------------------------ dashboard

@admin_bp.route("/")
@admin_required
def dashboard():
    today = utcnow() - timedelta(days=1)
    month = utcnow() - timedelta(days=30)
    paid_states = ["paid", "shipped", "delivered"]
    stats = {
        "review": Order.query.filter_by(status="payment_review").count(),
        "awaiting": Order.query.filter_by(status="awaiting_payment").count(),
        "to_ship": Order.query.filter_by(status="paid").count(),
        "orders_24h": Order.query.filter(Order.created_at >= today).count(),
        "revenue_30d": db.session.query(func.coalesce(func.sum(Order.total), 0))
        .filter(Order.status.in_(paid_states), Order.created_at >= month).scalar(),
        "revenue_all": db.session.query(func.coalesce(func.sum(Order.total), 0))
        .filter(Order.status.in_(paid_states)).scalar(),
        "products": Product.query.filter_by(is_active=True).count(),
        "messages": Message.query.filter_by(is_read=False).count(),
    }
    low_stock = (Product.query.filter(Product.is_active.is_(True), Product.made_to_order.is_(False),
                                      Product.stock <= 1).order_by(Product.stock).limit(8).all())
    recent = Order.query.order_by(Order.id.desc()).limit(8).all()
    days = []
    for i in range(13, -1, -1):
        start = (utcnow() - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        total = db.session.query(func.coalesce(func.sum(Order.total), 0)).filter(
            Order.status.in_(paid_states), Order.created_at >= start, Order.created_at < end).scalar()
        days.append({"date": start, "total": int(total or 0)})
    peak = max([d["total"] for d in days] + [1])
    setup_missing = not settings.get("card_number")
    return render_template("admin/dashboard.html", stats=stats, low_stock=low_stock, recent=recent,
                           days=days, peak=peak, setup_missing=setup_missing)


# ------------------------------------------------------------------ products

PRODUCT_TEXT_FIELDS = ("title", "short", "description", "sku", "size", "weight", "material", "colors", "care", "tags")


@admin_bp.route("/products")
@admin_required
def products():
    q = (request.args.get("q") or "").strip()
    cat = parse_int(request.args.get("cat"))
    state = request.args.get("state", "")
    query = Product.query
    if q:
        query = query.filter(or_(Product.title.ilike(f"%{q}%"), Product.sku.ilike(f"%{q}%"), Product.slug.ilike(f"%{q}%")))
    if cat:
        query = query.filter_by(category_id=cat)
    if state == "hidden":
        query = query.filter_by(is_active=False)
    elif state == "out":
        query = query.filter(Product.stock <= 0, Product.made_to_order.is_(False))
    elif state == "featured":
        query = query.filter_by(is_featured=True)
    pager = query.order_by(Product.id.desc()).paginate(page=parse_int(request.args.get("page"), 1, minimum=1),
                                                        per_page=30, error_out=False)
    return render_template("admin/products.html", pager=pager, categories=Category.query.order_by(Category.sort).all(),
                           q=q, cat=cat, state=state)


def _unique_slug(base: str, product_id: int | None = None) -> str:
    slug, n = base, 2
    while True:
        other = Product.query.filter_by(slug=slug).first()
        if other is None or other.id == product_id:
            return slug
        slug = f"{base}-{n}"
        n += 1


def _fill_product(p: Product) -> list[str]:
    f = request.form
    errors = []
    for name in PRODUCT_TEXT_FIELDS:
        setattr(p, name, (f.get(name) or "").strip())
    if len(p.title) < 2:
        errors.append("عنوان محصول لازم است.")
    p.slug = _unique_slug(slugify(f.get("slug") or p.title), p.id)
    p.category_id = parse_int(f.get("category_id")) or None
    p.kind = f.get("kind") if f.get("kind") in {"crochet", "painting", "other"} else "crochet"
    p.price = parse_int(f.get("price"), 0, minimum=0)
    p.compare_price = parse_int(f.get("compare_price"), 0, minimum=0)
    p.stock = parse_int(f.get("stock"), 0, minimum=0)
    p.making_days = parse_int(f.get("making_days"), 0, minimum=0, maximum=120)
    p.sort = parse_int(f.get("sort"), 0)
    p.made_to_order = f.get("made_to_order") == "1"
    p.is_featured = f.get("is_featured") == "1"
    p.is_active = f.get("is_active") == "1"
    if p.price <= 0:
        errors.append("قیمت باید بیشتر از صفر باشد.")
    return errors


def _save_uploads(p: Product) -> int:
    count = 0
    start = max([i.sort for i in p.images] + [0]) + 1
    for i, file in enumerate(request.files.getlist("images")):
        if not file or not file.filename:
            continue
        try:
            big, small = save_product_image(file)
        except ImageError as exc:
            flash(f"{file.filename}: {exc}", "error")
            continue
        p.images.append(ProductImage(path=big, path_sm=small, alt=p.title, sort=start + i))
        count += 1
    return count


@admin_bp.route("/products/new", methods=["GET", "POST"])
@admin_required
def product_new():
    p = Product(is_active=True, kind="crochet", stock=1)
    if request.method == "POST":
        errors = _fill_product(p)
        if errors:
            for e in errors:
                flash(e, "error")
        else:
            db.session.add(p)
            db.session.flush()
            _save_uploads(p)
            db.session.commit()
            audit("product_create", p.slug, p.title)
            flash("محصول ساخته شد.", "success")
            return redirect(url_for("admin.product_edit", pid=p.id))
    return render_template("admin/product_form.html", p=p, categories=Category.query.order_by(Category.sort).all())


@admin_bp.route("/products/<int:pid>", methods=["GET", "POST"])
@admin_required
def product_edit(pid):
    p = db.session.get(Product, pid) or abort(404)
    if request.method == "POST":
        errors = _fill_product(p)
        for img in p.images:
            alt = request.form.get(f"alt_{img.id}")
            if alt is not None:
                img.alt = alt.strip()[:160]
        if errors:
            db.session.rollback()
            for e in errors:
                flash(e, "error")
        else:
            added = _save_uploads(p)
            db.session.commit()
            audit("product_update", p.slug, f"+{added} images" if added else "")
            flash("تغییرات ذخیره شد.", "success")
            return redirect(url_for("admin.product_edit", pid=p.id))
    sold = db.session.query(func.coalesce(func.sum(OrderItem.qty), 0)).join(Order).filter(
        OrderItem.product_id == p.id, Order.status.in_(["paid", "shipped", "delivered"])).scalar()
    return render_template("admin/product_form.html", p=p, categories=Category.query.order_by(Category.sort).all(),
                           sold=sold)


@admin_bp.route("/products/<int:pid>/image/<int:iid>", methods=["POST"])
@admin_required
def product_image(pid, iid):
    p = db.session.get(Product, pid) or abort(404)
    img = next((i for i in p.images if i.id == iid), None) or abort(404)
    action = request.form.get("action")
    ordered = list(p.images)
    idx = ordered.index(img)
    if action == "delete":
        delete_media(img.path, img.path_sm)
        p.images.remove(img)
    elif action == "main":
        ordered.insert(0, ordered.pop(idx))
    elif action == "up" and idx > 0:
        ordered[idx - 1], ordered[idx] = ordered[idx], ordered[idx - 1]
    elif action == "down" and idx < len(ordered) - 1:
        ordered[idx + 1], ordered[idx] = ordered[idx], ordered[idx + 1]
    if action != "delete":
        for n, item in enumerate(ordered):
            item.sort = n
    db.session.commit()
    audit("product_image_" + (action or ""), p.slug)
    return redirect(url_for("admin.product_edit", pid=p.id) + "#images")


@admin_bp.route("/products/<int:pid>/action", methods=["POST"])
@admin_required
def product_action(pid):
    p = db.session.get(Product, pid) or abort(404)
    action = request.form.get("action")
    if action == "toggle":
        p.is_active = not p.is_active
        flash("وضعیت نمایش تغییر کرد.", "success")
    elif action == "feature":
        p.is_featured = not p.is_featured
    elif action == "duplicate":
        copy = Product(**{c.name: getattr(p, c.name) for c in Product.__table__.columns
                          if c.name not in {"id", "slug", "views", "created_at", "updated_at"}})
        copy.title = p.title + " (کپی)"
        copy.slug = _unique_slug(p.slug + "-copy")
        copy.is_active = False
        db.session.add(copy)
        db.session.commit()
        audit("product_duplicate", p.slug, copy.slug)
        flash("یک کپی پنهان ساخته شد؛ عکس‌ها را اضافه کن.", "success")
        return redirect(url_for("admin.product_edit", pid=copy.id))
    elif action == "delete":
        if request.form.get("confirm") != p.slug:
            flash("برای حذف، نامک (slug) محصول را دقیق تایپ کن.", "error")
            return redirect(url_for("admin.product_edit", pid=p.id))
        for img in p.images:
            delete_media(img.path, img.path_sm)
        # Past orders keep their own title/price copy; only the link to the product is cleared.
        OrderItem.query.filter_by(product_id=p.id).update({"product_id": None})
        db.session.delete(p)
        db.session.commit()
        audit("product_delete", p.slug, p.title)
        flash("محصول حذف شد.", "success")
        return redirect(url_for("admin.products"))
    db.session.commit()
    audit("product_" + (action or ""), p.slug)
    return redirect(request.referrer or url_for("admin.products"))


@admin_bp.route("/products/bulk", methods=["POST"])
@admin_required
def products_bulk():
    """Quick inline edit of price and stock from the product list."""
    changed = 0
    for key, value in request.form.items():
        if key.startswith("price_") or key.startswith("stock_"):
            field, pid = key.split("_", 1)
            p = db.session.get(Product, parse_int(pid))
            if p is None:
                continue
            n = parse_int(value, getattr(p, field), minimum=0)
            if n != getattr(p, field) and (field != "price" or n > 0):
                setattr(p, field, n)
                changed += 1
    db.session.commit()
    audit("products_bulk", "", f"{changed} changes")
    flash(f"{changed} تغییر ذخیره شد.", "success")
    return redirect(request.referrer or url_for("admin.products"))


# ------------------------------------------------------------------ categories

@admin_bp.route("/categories", methods=["GET", "POST"])
@admin_required
def categories():
    if request.method == "POST":
        cid = parse_int(request.form.get("id"))
        c = db.session.get(Category, cid) if cid else Category()
        if c is None:
            abort(404)
        if request.form.get("action") == "delete" and cid:
            if c.products.count():
                flash("این دسته محصول دارد؛ اول محصولات را جابه‌جا کن.", "error")
            else:
                db.session.delete(c)
                db.session.commit()
                audit("category_delete", c.slug)
                flash("دسته حذف شد.", "success")
            return redirect(url_for("admin.categories"))
        c.name = (request.form.get("name") or "").strip()[:120]
        if not c.name:
            flash("نام دسته لازم است.", "error")
            return redirect(url_for("admin.categories"))
        slug = slugify(request.form.get("slug") or c.name)
        clash = Category.query.filter_by(slug=slug).first()
        if clash and clash.id != c.id:
            slug = f"{slug}-{Category.query.count() + 1}"
        c.slug = slug
        c.description = (request.form.get("description") or "").strip()[:300]
        c.sort = parse_int(request.form.get("sort"))
        c.is_active = request.form.get("is_active") == "1"
        db.session.add(c)
        db.session.commit()
        audit("category_save", c.slug)
        flash("دسته ذخیره شد.", "success")
        return redirect(url_for("admin.categories"))
    rows = Category.query.order_by(Category.sort).all()
    return render_template("admin/categories.html", rows=rows)


# ------------------------------------------------------------------ orders

@admin_bp.route("/orders")
@admin_required
def orders_list():
    status = request.args.get("status", "")
    q = en_digits((request.args.get("q") or "").strip())
    query = Order.query
    if status in ORDER_STATUSES:
        query = query.filter_by(status=status)
    if q:
        query = query.filter(or_(Order.code.ilike(f"%{q}%"), Order.phone.ilike(f"%{q}%"),
                                 Order.customer_name.ilike(f"%{q}%")))
    pager = query.order_by(Order.id.desc()).paginate(page=parse_int(request.args.get("page"), 1, minimum=1),
                                                     per_page=30, error_out=False)
    counts = dict(db.session.query(Order.status, func.count(Order.id)).group_by(Order.status).all())
    return render_template("admin/orders.html", pager=pager, status=status, q=q, counts=counts,
                           statuses=ORDER_STATUSES)


@admin_bp.route("/orders/export.csv")
@admin_required
def orders_export():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["code", "date", "status", "name", "phone", "province", "city", "address", "postal_code",
                "subtotal", "shipping", "discount", "total", "items"])
    for o in Order.query.order_by(Order.id).all():
        w.writerow([o.code, o.created_at.isoformat(timespec="minutes"), o.status, o.customer_name, o.phone,
                    o.province, o.city, o.address, o.postal_code, o.subtotal, o.shipping, o.discount, o.total,
                    " | ".join(f"{i.title} x{i.qty}" for i in o.items)])
    audit("orders_export")
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=orders.csv"})


@admin_bp.route("/orders/<code>", methods=["GET", "POST"])
@admin_required
def order_detail(code):
    order = Order.query.filter_by(code=code).first_or_404()
    admin = current_admin().username
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "approve":
                payment = db.session.get(Payment, parse_int(request.form.get("payment_id"))) or abort(404)
                if payment.order_id != order.id:
                    abort(400)
                orders.approve_payment(payment, admin)
                audit("payment_approve", order.code, f"payment {payment.id}")
                flash("پرداخت تایید شد و سفارش به «در حال آماده‌سازی» رفت.", "success")
            elif action == "reject":
                payment = db.session.get(Payment, parse_int(request.form.get("payment_id"))) or abort(404)
                if payment.order_id != order.id:
                    abort(400)
                reason = (request.form.get("reason") or "").strip() or "رسید با مبلغ یا مشخصات سفارش مطابقت نداشت."
                orders.reject_payment(payment, admin, reason)
                audit("payment_reject", order.code, reason)
                flash("پرداخت رد شد؛ مشتری می‌تواند رسید درست را دوباره ثبت کند.", "success")
            elif action == "status":
                new = request.form.get("status")
                if new not in ORDER_STATUSES:
                    abort(400)
                old = order.status
                orders.set_status(order, new)
                tracking = (request.form.get("post_tracking") or "").strip()[:60]
                if tracking:
                    order.post_tracking = en_digits(tracking)
                db.session.commit()
                audit("order_status", order.code, f"{old} -> {new}")
                flash("وضعیت سفارش به‌روز شد.", "success")
            elif action == "note":
                order.admin_note = (request.form.get("admin_note") or "").strip()[:3000]
                db.session.commit()
                audit("order_note", order.code)
                flash("یادداشت ذخیره شد.", "success")
        except orders.OrderError as exc:
            db.session.rollback()
            flash(str(exc), "error")
        return redirect(url_for("admin.order_detail", code=order.code))
    return render_template("admin/order_detail.html", order=order, statuses=ORDER_STATUSES)


@admin_bp.route("/orders/<code>/invoice")
@admin_required
def order_invoice(code):
    order = Order.query.filter_by(code=code).first_or_404()
    return render_template("admin/invoice.html", order=order)


@admin_bp.route("/receipts/<path:name>")
@admin_required
def receipt(name):
    if not Payment.query.filter_by(receipt_path=f"receipts/{name}").first():
        abort(404)
    return send_from_directory(media_root() / "receipts", name)


@admin_bp.route("/orders/expire", methods=["POST"])
@admin_required
def orders_expire():
    n = orders.expire_unpaid(current_app.config["ORDER_HOLD_HOURS"])
    audit("orders_expire", "", str(n))
    flash(f"{n} سفارش پرداخت‌نشده لغو شد و موجودی‌شان برگشت.", "success")
    return redirect(url_for("admin.orders_list"))


# ------------------------------------------------------------------ coupons

@admin_bp.route("/coupons", methods=["GET", "POST"])
@admin_required
def coupons():
    if request.method == "POST":
        cid = parse_int(request.form.get("id"))
        c = db.session.get(Coupon, cid) if cid else Coupon()
        if c is None:
            abort(404)
        if request.form.get("action") == "delete" and cid:
            db.session.delete(c)
            db.session.commit()
            audit("coupon_delete", c.code)
            return redirect(url_for("admin.coupons"))
        code = en_digits((request.form.get("code") or "").strip().upper())[:32]
        if not code or (Coupon.query.filter_by(code=code).first() not in (None, c)):
            flash("کد خالی یا تکراری است.", "error")
            return redirect(url_for("admin.coupons"))
        c.code = code
        c.percent = parse_int(request.form.get("percent"), 0, minimum=0, maximum=100)
        c.amount = parse_int(request.form.get("amount"), 0, minimum=0)
        c.min_total = parse_int(request.form.get("min_total"), 0, minimum=0)
        c.max_uses = parse_int(request.form.get("max_uses"), 0, minimum=0)
        days = parse_int(request.form.get("days"), 0, minimum=0)
        if days:
            c.expires_at = utcnow() + timedelta(days=days)
        c.is_active = request.form.get("is_active") == "1"
        db.session.add(c)
        db.session.commit()
        audit("coupon_save", c.code)
        flash("کد تخفیف ذخیره شد.", "success")
        return redirect(url_for("admin.coupons"))
    return render_template("admin/coupons.html", rows=Coupon.query.order_by(Coupon.id.desc()).all())


# ------------------------------------------------------------------ messages & subscribers

@admin_bp.route("/messages", methods=["GET", "POST"])
@admin_required
def messages():
    if request.method == "POST":
        m = db.session.get(Message, parse_int(request.form.get("id"))) or abort(404)
        if request.form.get("action") == "delete":
            db.session.delete(m)
        else:
            m.is_read = not m.is_read
        db.session.commit()
        return redirect(url_for("admin.messages"))
    return render_template("admin/messages.html", rows=Message.query.order_by(Message.id.desc()).limit(300).all(),
                           subscribers=Subscriber.query.order_by(Subscriber.id.desc()).all())


@admin_bp.route("/subscribers.csv")
@admin_required
def subscribers_export():
    rows = "\n".join(f"{s.contact},{s.created_at.date()}" for s in Subscriber.query.order_by(Subscriber.id))
    return Response("﻿contact,date\n" + rows, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=subscribers.csv"})


# ------------------------------------------------------------------ settings

SETTING_GROUPS = {
    "general": ["site_name", "site_name_fa", "tagline", "hero_title", "hero_subtitle", "about_title", "about_text",
                "handmade_note", "phone", "email", "instagram", "telegram", "address"],
    "payment": ["card_to_card_enabled", "card_number", "card_holder", "card_bank", "sheba", "card_instructions",
                "gateway_enabled"],
    "shipping": ["shipping_fee", "free_shipping_over", "processing_days"],
}
CHECKBOXES = {"card_to_card_enabled", "gateway_enabled"}


@admin_bp.route("/settings/<group>", methods=["GET", "POST"])
@admin_required
def settings_page(group):
    if group not in SETTING_GROUPS:
        abort(404)
    if request.method == "POST":
        values = {}
        for key in SETTING_GROUPS[group]:
            if key in CHECKBOXES:
                values[key] = "1" if request.form.get(key) == "1" else "0"
            else:
                values[key] = request.form.get(key, "")
        if group == "payment":
            values["card_number"] = en_digits(values["card_number"]).replace(" ", "").replace("-", "")
            values["sheba"] = en_digits(values["sheba"]).replace(" ", "").upper()
            if values["card_number"] and not valid_card(values["card_number"]):
                flash("شماره کارت معتبر نیست (۱۶ رقم را دوباره بررسی کن).", "error")
                return redirect(url_for("admin.settings_page", group=group))
            if values["sheba"] and not (values["sheba"].startswith("IR") and len(values["sheba"]) == 26):
                flash("شبا باید با IR شروع شود و ۲۶ کاراکتر باشد.", "error")
                return redirect(url_for("admin.settings_page", group=group))
        if group == "shipping":
            for key in ("shipping_fee", "free_shipping_over"):
                values[key] = str(parse_int(values[key], 0, minimum=0))
        settings.save(values)
        audit("settings_" + group)
        flash("تنظیمات ذخیره شد.", "success")
        return redirect(url_for("admin.settings_page", group=group))
    gateway_ready = bool(current_app.config.get("ZARINPAL_MERCHANT_ID") and current_app.config.get("PUBLIC_BASE_URL"))
    return render_template("admin/settings.html", group=group, keys=SETTING_GROUPS[group], s=settings.get_all(),
                           defaults=DEFAULTS, gateway_ready=gateway_ready,
                           sandbox=current_app.config.get("ZARINPAL_SANDBOX"))


# ------------------------------------------------------------------ admins & security

@admin_bp.route("/account", methods=["GET", "POST"])
@admin_required
def account():
    me = current_admin()
    pending_secret = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "password":
            if not me.check_password(request.form.get("current") or ""):
                flash("رمز فعلی درست نیست.", "error")
            elif len(request.form.get("new") or "") < 10:
                flash("رمز جدید دست‌کم ۱۰ کاراکتر باشد.", "error")
            elif request.form.get("new") != request.form.get("repeat"):
                flash("تکرار رمز جدید یکسان نیست.", "error")
            else:
                me.set_password(request.form["new"])
                db.session.commit()
                start_session(me)
                audit("password_change")
                flash("رمز عوض شد؛ نشست‌های دیگر بسته شدند.", "success")
            return redirect(url_for("admin.account"))
        if action == "totp_start":
            pending_secret = new_totp_secret()
        elif action == "totp_confirm":
            secret = request.form.get("secret") or ""
            if verify_totp(me, request.form.get("code") or "", secret=secret):
                me.totp_secret = secret
                db.session.commit()
                audit("totp_enable")
                flash("ورود دومرحله‌ای فعال شد.", "success")
                return redirect(url_for("admin.account"))
            flash("کد درست نبود؛ دوباره اسکن کن و کد تازه بزن.", "error")
            pending_secret = secret
        elif action == "totp_disable":
            if me.check_password(request.form.get("current") or ""):
                me.totp_secret = ""
                db.session.commit()
                audit("totp_disable")
                flash("ورود دومرحله‌ای خاموش شد.", "success")
            else:
                flash("رمز فعلی درست نیست.", "error")
            return redirect(url_for("admin.account"))
        elif action == "add_admin":
            username = (request.form.get("username") or "").strip()[:64]
            password = request.form.get("password") or ""
            if len(username) < 3 or len(password) < 10:
                flash("نام کاربری دست‌کم ۳ و رمز دست‌کم ۱۰ کاراکتر.", "error")
            elif AdminUser.query.filter(func.lower(AdminUser.username) == username.lower()).first():
                flash("این نام کاربری وجود دارد.", "error")
            else:
                u = AdminUser(username=username)
                u.set_password(password)
                db.session.add(u)
                db.session.commit()
                audit("admin_create", username)
                flash("مدیر جدید ساخته شد.", "success")
            return redirect(url_for("admin.account"))
        elif action == "toggle_admin":
            u = db.session.get(AdminUser, parse_int(request.form.get("id"))) or abort(404)
            if u.id == me.id:
                flash("نمی‌توانی حساب خودت را غیرفعال کنی.", "error")
            else:
                u.is_active = not u.is_active
                u.session_version = (u.session_version or 0) + 1
                db.session.commit()
                audit("admin_toggle", u.username, str(u.is_active))
            return redirect(url_for("admin.account"))
    uri = provisioning_uri(me, pending_secret) if pending_secret else None
    return render_template("admin/account.html", me=me, admins=AdminUser.query.order_by(AdminUser.id).all(),
                           pending_secret=pending_secret, uri=uri)


@admin_bp.route("/audit")
@admin_required
def audit_log():
    rows = AuditLog.query.order_by(AuditLog.id.desc()).limit(400).all()
    return render_template("admin/audit.html", rows=rows)


__all__ = ["admin_bp", "client_ip"]
