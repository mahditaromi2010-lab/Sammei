from __future__ import annotations

import secrets

from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db
from .utils import utcnow


class Setting(db.Model):
    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text, default="")


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(80), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(300), default="")
    sort = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    products = db.relationship("Product", back_populates="category", lazy="dynamic")


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(90), unique=True, nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), index=True)
    category = db.relationship("Category", back_populates="products")
    kind = db.Column(db.String(20), default="crochet")  # crochet | painting | other
    short = db.Column(db.String(300), default="")
    description = db.Column(db.Text, default="")
    price = db.Column(db.Integer, nullable=False, default=0)          # Toman
    compare_price = db.Column(db.Integer, default=0)                  # Old price, shown struck through
    stock = db.Column(db.Integer, default=0)
    made_to_order = db.Column(db.Boolean, default=False)              # Can be ordered even with zero stock
    making_days = db.Column(db.Integer, default=0)
    sku = db.Column(db.String(40), default="")
    size = db.Column(db.String(120), default="")
    weight = db.Column(db.String(60), default="")
    material = db.Column(db.String(200), default="")
    colors = db.Column(db.String(200), default="")
    care = db.Column(db.String(300), default="")
    tags = db.Column(db.String(300), default="")
    is_featured = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    sort = db.Column(db.Integer, default=0)
    views = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    images = db.relationship("ProductImage", back_populates="product", order_by="ProductImage.sort",
                             cascade="all, delete-orphan")

    @property
    def main_image(self):
        return self.images[0] if self.images else None

    @property
    def in_stock(self) -> bool:
        return self.made_to_order or (self.stock or 0) > 0

    @property
    def discount_percent(self) -> int:
        if self.compare_price and self.compare_price > self.price > 0:
            return round(100 - self.price * 100 / self.compare_price)
        return 0

    def max_qty(self) -> int:
        return 20 if self.made_to_order else max(0, self.stock or 0)


class ProductImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), index=True)
    product = db.relationship("Product", back_populates="images")
    path = db.Column(db.String(200), nullable=False)      # relative to MEDIA_ROOT
    path_sm = db.Column(db.String(200), nullable=False)
    alt = db.Column(db.String(160), default="")
    sort = db.Column(db.Integer, default=0)


class Coupon(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False, index=True)
    percent = db.Column(db.Integer, default=0)
    amount = db.Column(db.Integer, default=0)
    min_total = db.Column(db.Integer, default=0)
    max_uses = db.Column(db.Integer, default=0)   # 0 = unlimited
    used = db.Column(db.Integer, default=0)
    expires_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    def discount_for(self, subtotal: int) -> int:
        if not self.is_active or subtotal < (self.min_total or 0):
            return 0
        if self.max_uses and self.used >= self.max_uses:
            return 0
        if self.expires_at and self.expires_at < utcnow():
            return 0
        value = subtotal * (self.percent or 0) // 100 if self.percent else (self.amount or 0)
        return max(0, min(value, subtotal))


ORDER_STATUSES = {
    "awaiting_payment": "در انتظار پرداخت",
    "payment_review": "در حال بررسی پرداخت",
    "payment_rejected": "پرداخت تایید نشد",
    "paid": "پرداخت‌شده، در حال آماده‌سازی",
    "shipped": "ارسال‌شده",
    "delivered": "تحویل‌شده",
    "cancelled": "لغوشده",
}
OPEN_STATUSES = {"awaiting_payment", "payment_review", "payment_rejected"}
STOCK_HELD_STATUSES = {"awaiting_payment", "payment_review", "payment_rejected", "paid", "shipped", "delivered"}


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(16), unique=True, nullable=False, index=True)
    access_token = db.Column(db.String(48), nullable=False, default=lambda: secrets.token_urlsafe(24))
    status = db.Column(db.String(24), default="awaiting_payment", index=True)
    customer_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False, index=True)
    email = db.Column(db.String(160), default="")
    province = db.Column(db.String(60), default="")
    city = db.Column(db.String(80), default="")
    address = db.Column(db.String(500), default="")
    postal_code = db.Column(db.String(20), default="")
    note = db.Column(db.String(500), default="")
    subtotal = db.Column(db.Integer, default=0)
    shipping = db.Column(db.Integer, default=0)
    discount = db.Column(db.Integer, default=0)
    coupon_code = db.Column(db.String(32), default="")
    total = db.Column(db.Integer, default=0)
    payment_method = db.Column(db.String(24), default="card_to_card")
    post_tracking = db.Column(db.String(60), default="")
    admin_note = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    items = db.relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    payments = db.relationship("Payment", back_populates="order", order_by="Payment.id.desc()",
                               cascade="all, delete-orphan")

    @property
    def status_label(self) -> str:
        return ORDER_STATUSES.get(self.status, self.status)

    @property
    def latest_payment(self):
        return self.payments[0] if self.payments else None


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), index=True)
    order = db.relationship("Order", back_populates="items")
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=True)
    product = db.relationship("Product")
    title = db.Column(db.String(160))
    price = db.Column(db.Integer)
    qty = db.Column(db.Integer)
    image = db.Column(db.String(200), default="")

    @property
    def line_total(self) -> int:
        return (self.price or 0) * (self.qty or 0)


PAYMENT_STATUSES = {
    "pending": "در انتظار",
    "submitted": "رسید ارسال شد",
    "approved": "تایید شد",
    "rejected": "رد شد",
    "failed": "ناموفق",
}


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), index=True)
    order = db.relationship("Order", back_populates="payments")
    method = db.Column(db.String(24), default="card_to_card")  # card_to_card | zarinpal
    amount = db.Column(db.Integer, default=0)
    status = db.Column(db.String(16), default="pending", index=True)
    payer_card_last4 = db.Column(db.String(4), default="")
    ref_number = db.Column(db.String(40), default="")       # bank tracking / reference number
    paid_at_text = db.Column(db.String(40), default="")     # date/time the customer says they paid
    receipt_path = db.Column(db.String(200), default="")    # private, admin-only
    gateway_authority = db.Column(db.String(64), default="", index=True)
    gateway_ref_id = db.Column(db.String(64), default="")
    reject_reason = db.Column(db.String(300), default="")
    reviewed_by = db.Column(db.String(64), default="")
    reviewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    @property
    def status_label(self) -> str:
        return PAYMENT_STATUSES.get(self.status, self.status)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120))
    contact = db.Column(db.String(160))
    body = db.Column(db.Text)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)


class Subscriber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    contact = db.Column(db.String(160), unique=True)
    created_at = db.Column(db.DateTime, default=utcnow)


class AdminUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    totp_secret = db.Column(db.String(64), default="")
    totp_last_step = db.Column(db.Integer, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    failed_logins = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    session_version = db.Column(db.Integer, default=1)
    last_login = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)
        self.session_version = (self.session_version or 0) + 1

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin = db.Column(db.String(64))
    action = db.Column(db.String(64))
    target = db.Column(db.String(120), default="")
    detail = db.Column(db.String(500), default="")
    ip = db.Column(db.String(64), default="")
    created_at = db.Column(db.DateTime, default=utcnow, index=True)
