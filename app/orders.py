"""Cart and order logic, kept out of the views so both shop and admin share it."""
from __future__ import annotations

import secrets
from datetime import timedelta

from flask import session

from . import settings
from .extensions import db
from .models import STOCK_HELD_STATUSES, Coupon, Order, OrderItem, Payment, Product
from .utils import utcnow

CART_KEY = "cart"


class OrderError(ValueError):
    pass


# ------------------------------------------------------------------ cart (session)

def cart_raw() -> dict[str, int]:
    raw = session.get(CART_KEY) or {}
    return {str(k): int(v) for k, v in raw.items() if str(k).isdigit() and int(v) > 0}


def cart_set(product_id: int, qty: int) -> None:
    raw = cart_raw()
    if qty <= 0:
        raw.pop(str(product_id), None)
    else:
        raw[str(product_id)] = qty
    session[CART_KEY] = raw
    session.modified = True


def cart_add(product: Product, qty: int = 1) -> int:
    raw = cart_raw()
    new_qty = min(raw.get(str(product.id), 0) + max(1, qty), product.max_qty())
    if new_qty <= 0:
        raise OrderError("این محصول فعلاً موجود نیست.")
    cart_set(product.id, new_qty)
    return new_qty


def cart_clear() -> None:
    session.pop(CART_KEY, None)
    session.pop("coupon", None)


def cart_count() -> int:
    return sum(cart_raw().values())


def cart_lines() -> list[dict]:
    raw = cart_raw()
    if not raw:
        return []
    products = {p.id: p for p in Product.query.filter(Product.id.in_([int(k) for k in raw])).all()}
    lines, changed = [], False
    for pid, qty in raw.items():
        p = products.get(int(pid))
        if p is None or not p.is_active or not p.in_stock:
            changed = True
            continue
        q = min(qty, p.max_qty())
        if q != qty:
            changed = True
        lines.append({"product": p, "qty": q, "total": q * p.price})
    if changed:
        session[CART_KEY] = {str(l["product"].id): l["qty"] for l in lines}
    return lines


def find_coupon(code: str) -> Coupon | None:
    code = (code or "").strip().upper()
    return Coupon.query.filter_by(code=code).first() if code else None


def totals(lines: list[dict], coupon_code: str = "") -> dict:
    subtotal = sum(l["total"] for l in lines)
    coupon = find_coupon(coupon_code)
    discount = coupon.discount_for(subtotal) if coupon else 0
    fee = settings.get_int("shipping_fee", 0)
    free_over = settings.get_int("free_shipping_over", 0)
    shipping = 0 if not lines or (free_over and subtotal - discount >= free_over) else fee
    return {"subtotal": subtotal, "discount": discount, "shipping": shipping,
            "total": max(0, subtotal - discount + shipping),
            "coupon": coupon if discount else None, "free_over": free_over}


# ------------------------------------------------------------------ orders

def _new_code() -> str:
    while True:
        code = "S" + "".join(secrets.choice("23456789") for _ in range(7))
        if not Order.query.filter_by(code=code).first():
            return code


def create_order(lines: list[dict], customer: dict, method: str, coupon_code: str = "") -> Order:
    if not lines:
        raise OrderError("سبد خرید خالی است.")
    t = totals(lines, coupon_code)
    order = Order(code=_new_code(), payment_method=method, subtotal=t["subtotal"], discount=t["discount"],
                  shipping=t["shipping"], total=t["total"],
                  coupon_code=t["coupon"].code if t["coupon"] else "", **customer)
    for line in lines:
        # Lock-free stock check + decrement in the same transaction.
        p = db.session.get(Product, line["product"].id)
        if p is None or not p.is_active:
            raise OrderError("یکی از محصولات سبد دیگر موجود نیست.")
        if not p.made_to_order:
            if (p.stock or 0) < line["qty"]:
                raise OrderError(f"موجودی «{p.title}» کافی نیست.")
            p.stock -= line["qty"]
        img = p.main_image.path_sm if p.main_image else ""
        order.items.append(OrderItem(product_id=p.id, title=p.title, price=p.price, qty=line["qty"], image=img))
    if t["coupon"]:
        t["coupon"].used = (t["coupon"].used or 0) + 1
    order.payments.append(Payment(method=method, amount=order.total, status="pending"))
    db.session.add(order)
    db.session.commit()
    return order


def _restore_stock(order: Order) -> None:
    for item in order.items:
        if item.product and not item.product.made_to_order:
            item.product.stock = (item.product.stock or 0) + item.qty


def set_status(order: Order, new_status: str) -> None:
    """Change status and keep stock consistent when an order is cancelled or revived."""
    old = order.status
    if old == new_status:
        return
    if old in STOCK_HELD_STATUSES and new_status == "cancelled":
        _restore_stock(order)
    elif old == "cancelled" and new_status in STOCK_HELD_STATUSES:
        for item in order.items:
            p = item.product
            if p and not p.made_to_order:
                if (p.stock or 0) < item.qty:
                    raise OrderError(f"موجودی «{p.title}» برای بازگرداندن سفارش کافی نیست.")
                p.stock -= item.qty
    order.status = new_status


def submit_receipt(order: Order, payment: Payment, *, last4: str, ref: str, paid_at: str, receipt_path: str) -> None:
    payment.payer_card_last4 = last4
    payment.ref_number = ref
    payment.paid_at_text = paid_at
    payment.receipt_path = receipt_path
    payment.status = "submitted"
    payment.reject_reason = ""
    order.status = "payment_review"
    db.session.commit()


def approve_payment(payment: Payment, admin: str) -> None:
    payment.status = "approved"
    payment.reviewed_by = admin
    payment.reviewed_at = utcnow()
    if payment.order.status in {"awaiting_payment", "payment_review", "payment_rejected", "cancelled"}:
        set_status(payment.order, "paid")
    db.session.commit()


def reject_payment(payment: Payment, admin: str, reason: str) -> None:
    payment.status = "rejected"
    payment.reject_reason = reason[:300]
    payment.reviewed_by = admin
    payment.reviewed_at = utcnow()
    payment.order.status = "payment_rejected"
    # A fresh pending payment lets the customer upload a corrected receipt.
    payment.order.payments.append(Payment(method=payment.method, amount=payment.order.total, status="pending"))
    db.session.commit()


def expire_unpaid(hours: int) -> int:
    """Cancel card-to-card orders that never got a receipt, releasing their stock."""
    cutoff = utcnow() - timedelta(hours=hours)
    stale = Order.query.filter(Order.status == "awaiting_payment", Order.created_at < cutoff).all()
    for order in stale:
        set_status(order, "cancelled")
        order.admin_note = ((order.admin_note or "") + "\nلغو خودکار: رسید پرداخت در مهلت ثبت نشد.").strip()
    db.session.commit()
    return len(stale)
