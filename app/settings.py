"""Shop settings stored in the database and edited from the admin panel."""
from __future__ import annotations

from flask import g

from .extensions import db
from .models import Setting

DEFAULTS: dict[str, str] = {
    # General
    "site_name": "Sammiie",
    "site_name_fa": "سمی",
    "tagline": "عروسک‌های بافتنی و نقاشی‌های دست‌ساز",
    "hero_title": "دست‌ساز، با عشق",
    "hero_subtitle": "عروسک‌های بافتنی و تابلوهای نقاشی، برای دنیایی مهربان‌تر",
    "about_title": "داستان ما",
    "about_text": (
        "سمی یک دنیای کوچک و گرم است؛ جایی که هر عروسک با کاموا و حوصله، دانه‌به‌دانه بافته می‌شود "
        "و هر تابلو با قلم‌مو و رنگ اکریلیک، شب‌به‌شب جان می‌گیرد. هیچ دو کاری دقیقاً مثل هم نیستند و "
        "همین، آن‌ها را مال تو می‌کند."
    ),
    "phone": "",
    "email": "",
    "instagram": "",
    "telegram": "",
    "address": "",
    "handmade_note": "همه‌ی محصولات دست‌ساز هستند؛ تفاوت جزئی در رنگ و اندازه طبیعی است و هر کار را منحصربه‌فرد می‌کند.",
    # Shipping
    "shipping_fee": "90000",
    "free_shipping_over": "3000000",
    "processing_days": "۲ تا ۴ روز کاری",
    # Card to card
    "card_number": "",
    "card_holder": "",
    "card_bank": "",
    "sheba": "",
    "card_instructions": "مبلغ سفارش را دقیقاً کارت‌به‌کارت کنید، سپس تصویر رسید و شماره پیگیری را همین‌جا ثبت کنید. پس از تایید، سفارش شما آماده‌ی ارسال می‌شود.",
    # Gateway
    "gateway_enabled": "0",
    "card_to_card_enabled": "1",
}


def get_all() -> dict[str, str]:
    if "settings" not in g:
        values = dict(DEFAULTS)
        for row in Setting.query.all():
            values[row.key] = row.value or ""
        g.settings = values
    return g.settings


def get(key: str, default: str = "") -> str:
    return get_all().get(key, default)


def get_int(key: str, default: int = 0) -> int:
    try:
        return int(get(key, str(default)) or default)
    except ValueError:
        return default


def save(values: dict[str, str]) -> None:
    for key, value in values.items():
        if key not in DEFAULTS:
            continue
        row = db.session.get(Setting, key)
        if row is None:
            row = Setting(key=key)
            db.session.add(row)
        row.value = (value or "").strip()
    db.session.commit()
    g.pop("settings", None)
