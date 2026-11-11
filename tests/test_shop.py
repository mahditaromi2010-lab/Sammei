import io
import re

import pytest
from PIL import Image

from app import create_app, settings
from app.cli import seed_catalog
from app.config import TestConfig
from app.extensions import db
from app.models import AdminUser, Coupon, Order, Product


class Cfg(TestConfig):
    pass


@pytest.fixture()
def app(tmp_path):
    Cfg.MEDIA_ROOT = tmp_path / "media"
    app = create_app(Cfg)
    with app.app_context():
        seed_catalog()
        settings.save({"card_number": "6037991234567893", "card_holder": "تست", "card_bank": "ملی"})
        u = AdminUser(username="boss")
        u.set_password("super-secret-1")
        db.session.add(u)
        db.session.commit()
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "pink").save(buf, "PNG")
    buf.seek(0)
    return buf


CUSTOMER = {"customer_name": "مهسا تست", "phone": "۰۹۱۲۳۴۵۶۷۸۹", "province": "فارس", "city": "شیراز",
            "address": "خیابان زند، کوچه ۱۲، پلاک ۴", "postal_code": "7134567890", "method": "card_to_card"}


def place_order(app, client, slug="chef-chick", qty=1):
    with app.app_context():
        pid = Product.query.filter_by(slug=slug).first().id
    client.post("/cart/add", data={"product_id": pid, "qty": qty})
    r = client.post("/checkout", data=CUSTOMER)
    assert r.status_code == 302, r.data.decode()[:500]
    m = re.search(r"/order/(S\d+)\?t=([\w-]+)", r.headers["Location"])
    return m.group(1), m.group(2), pid


def login(client):
    return client.post("/manage/login", data={"username": "boss", "password": "super-secret-1"})


def test_public_pages(client):
    for url in ["/", "/shop", "/shop?cat=paintings", "/shop?q=خرس", "/product/yellow-giraffe", "/gallery",
                "/about", "/contact", "/cart", "/track", "/sitemap.xml", "/robots.txt"]:
        assert client.get(url).status_code == 200, url
    assert client.get("/product/missing").status_code == 404


def test_catalog_seeded(app):
    with app.app_context():
        assert Product.query.count() == 69
        assert all(p.images for p in Product.query.all())


def test_full_card_to_card_flow(app, client):
    code, token, pid = place_order(app, client, qty=2)
    with app.app_context():
        assert db.session.get(Product, pid).stock == 1  # 3 - 2 reserved
        order = Order.query.filter_by(code=code).first()
        assert order.phone == "09123456789" and order.status == "awaiting_payment"
        assert order.total == 690000 * 2 + 90000

    page = client.get(f"/order/{code}?t={token}").data.decode()
    assert "6037" in page and "کارت" in page
    assert client.get(f"/order/{code}?t=wrong").status_code == 404

    r = client.post(f"/order/{code}/receipt?t={token}", data={"last4": "1234", "ref": "998877", "receipt": (png_bytes(), "r.png")},
                    content_type="multipart/form-data")
    assert r.status_code == 302
    with app.app_context():
        order = Order.query.filter_by(code=code).first()
        assert order.status == "payment_review"
        pay_id = order.latest_payment.id
        receipt = order.latest_payment.receipt_path

    # Receipts are private
    assert client.get("/media/" + receipt).status_code == 404
    assert client.get("/manage/receipts/" + receipt.removeprefix("receipts/")).status_code == 302

    login(client)
    assert client.get("/manage/receipts/" + receipt.removeprefix("receipts/")).status_code == 200
    client.post(f"/manage/orders/{code}", data={"action": "approve", "payment_id": pay_id})
    with app.app_context():
        assert Order.query.filter_by(code=code).first().status == "paid"
    client.post(f"/manage/orders/{code}", data={"action": "status", "status": "shipped", "post_tracking": "1234567890"})
    assert "1234567890" in client.get(f"/order/{code}?t={token}").data.decode().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))


def test_reject_then_resubmit_and_cancel_restores_stock(app, client):
    code, token, pid = place_order(app, client)
    client.post(f"/order/{code}/receipt?t={token}", data={"last4": "1234", "ref": "5555", "receipt": (png_bytes(), "r.png")},
                content_type="multipart/form-data")
    login(client)
    with app.app_context():
        pay_id = Order.query.filter_by(code=code).first().latest_payment.id
    client.post(f"/manage/orders/{code}", data={"action": "reject", "payment_id": pay_id, "reason": "مبلغ کم بود"})
    page = client.get(f"/order/{code}?t={token}").data.decode()
    assert "مبلغ کم بود" in page
    r = client.post(f"/order/{code}/receipt?t={token}", data={"last4": "4321", "ref": "6666", "receipt": (png_bytes(), "r.png")},
                    content_type="multipart/form-data")
    with app.app_context():
        assert Order.query.filter_by(code=code).first().status == "payment_review"
    client.post(f"/manage/orders/{code}", data={"action": "status", "status": "cancelled"})
    with app.app_context():
        assert db.session.get(Product, pid).stock == 3


def test_cannot_oversell(app, client):
    with app.app_context():
        p = Product.query.filter_by(slug="firefly-forest").first()
        pid = p.id
    client.post("/cart/add", data={"product_id": pid, "qty": 5})
    r = client.get("/cart").data.decode()
    assert "تک‌نسخه" in r
    place_order(app, client, slug="firefly-forest")
    with app.app_context():
        assert db.session.get(Product, pid).stock == 0
    page = client.get("/product/firefly-forest").data.decode()
    assert "فروخته شد" in page


def test_checkout_validation(app, client):
    with app.app_context():
        pid = Product.query.filter_by(slug="brown-bear").first().id
    client.post("/cart/add", data={"product_id": pid})
    r = client.post("/checkout", data={**CUSTOMER, "phone": "123", "postal_code": "12"})
    assert r.status_code == 200
    body = r.data.decode()
    assert "۰۹" in body and "کد پستی" in body


def test_coupon(app, client):
    with app.app_context():
        db.session.add(Coupon(code="YALDA", percent=10))
        db.session.commit()
        pid = Product.query.filter_by(slug="brown-bear").first().id
    client.post("/cart/add", data={"product_id": pid})
    client.post("/cart/coupon", data={"code": "yalda"})
    r = client.post("/checkout", data=CUSTOMER)
    code = re.search(r"/order/(S\d+)", r.headers["Location"]).group(1)
    with app.app_context():
        o = Order.query.filter_by(code=code).first()
        assert o.discount == 59000 and o.coupon_code == "YALDA"


def test_admin_requires_login_and_crud(app, client):
    assert client.get("/manage/").status_code == 302
    assert login(client).status_code == 302
    for url in ["/manage/", "/manage/products", "/manage/products/new", "/manage/categories", "/manage/orders",
                "/manage/coupons", "/manage/messages", "/manage/settings/payment", "/manage/settings/general",
                "/manage/settings/shipping", "/manage/account", "/manage/audit", "/manage/products/1"]:
        assert client.get(url).status_code == 200, url
    with app.app_context():
        cat = Product.query.first().category_id
    r = client.post("/manage/products/new", data={"title": "خرگوش جدید", "price": "۵۰۰٬۰۰۰", "stock": "4", "category_id": cat,
                                                 "is_active": "1", "kind": "crochet", "material": "کاموا",
                                                 "images": (png_bytes(), "a.png")}, content_type="multipart/form-data")
    assert r.status_code == 302
    with app.app_context():
        p = Product.query.filter_by(title="خرگوش جدید").first()
        assert p.price == 500000 and len(p.images) == 1 and p.material == "کاموا"
        pid = p.id
    assert client.get("/product/" + p.slug).status_code == 200
    client.post("/manage/products/bulk", data={f"price_{pid}": "650000", f"stock_{pid}": "9"})
    with app.app_context():
        p = db.session.get(Product, pid)
        assert (p.price, p.stock) == (650000, 9)
    client.post(f"/manage/products/{pid}/action", data={"action": "delete", "confirm": p.slug})
    with app.app_context():
        assert db.session.get(Product, pid) is None


def test_admin_bad_login_and_bad_card(app, client):
    r = client.post("/manage/login", data={"username": "boss", "password": "nope"})
    assert "اشتباه" in r.data.decode()
    login(client)
    client.post("/manage/settings/payment", data={"card_number": "1234567812345678"})
    with app.app_context():
        assert settings.get("card_number") == "6037991234567893"


def test_receipt_rejects_non_image(app, client):
    code, token, _ = place_order(app, client)
    r = client.post(f"/order/{code}/receipt?t={token}",
                    data={"last4": "1234", "ref": "5555", "receipt": (io.BytesIO(b"<?php evil ?>"), "x.php")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "تصویر معتبری نیست" in r.data.decode()


def test_utils():
    from app.utils import jdate, money, valid_card
    from datetime import datetime
    assert money(1250000) == "۱٬۲۵۰٬۰۰۰"
    assert jdate(datetime(2026, 11, 11, 10, 0), with_time=False) == "۱۴۰۵/۰۸/۲۰"
    assert valid_card("6037991234567893") and not valid_card("6037991234567890")
