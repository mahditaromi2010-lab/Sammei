"""Small helpers: Persian digits, money, Jalali dates, slugs, iban/card formatting."""
from __future__ import annotations

import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
TO_EN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
TEHRAN = timezone(timedelta(hours=3, minutes=30))


def fa(value) -> str:
    return str(value if value is not None else "").translate(FA_DIGITS)


def en_digits(value: str | None) -> str:
    return (value or "").translate(TO_EN_DIGITS)


def money(value) -> str:
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        n = 0
    return fa(f"{n:,}").replace(",", "٬")


def parse_int(value, default: int = 0, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        n = int(en_digits(str(value)).replace(",", "").replace("٬", "").strip())
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        n = max(minimum, n)
    if maximum is not None:
        n = min(maximum, n)
    return n


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKC", en_digits(text or "")).strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:80] or secrets.token_hex(4)


def group_digits(value: str, size: int = 4, sep: str = " ") -> str:
    digits = re.sub(r"\D", "", en_digits(value))
    return sep.join(digits[i:i + size] for i in range(0, len(digits), size))


def mask_card(value: str) -> str:
    d = re.sub(r"\D", "", en_digits(value))
    return f"{d[:4]}-****-****-{d[-4:]}" if len(d) >= 8 else d


def valid_iran_mobile(value: str) -> bool:
    return bool(re.fullmatch(r"09\d{9}", en_digits(value).strip()))


def valid_card(value: str) -> bool:
    """16-digit bank card with a valid Luhn check digit (Shetab cards use Luhn)."""
    d = re.sub(r"\D", "", en_digits(value))
    if len(d) != 16:
        return False
    total = 0
    for i, ch in enumerate(d):
        n = int(ch)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


# ------------------------------------------------------------------ Jalali calendar

def _g2j(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + (days // 31), 1 + (days % 31)
    else:
        jm, jd = 7 + ((days - 186) // 30), 1 + ((days - 186) % 30)
    return jy, jm, jd


JALALI_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]


def jdate(dt: datetime | None, with_time: bool = True, long: bool = False) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(TEHRAN)
    y, m, d = _g2j(local.year, local.month, local.day)
    out = f"{d} {JALALI_MONTHS[m - 1]} {y}" if long else f"{y}/{m:02d}/{d:02d}"
    if with_time:
        out += f" - {local.hour:02d}:{local.minute:02d}"
    return fa(out)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


PROVINCES = [
    "آذربایجان شرقی", "آذربایجان غربی", "اردبیل", "اصفهان", "البرز", "ایلام", "بوشهر", "تهران",
    "چهارمحال و بختیاری", "خراسان جنوبی", "خراسان رضوی", "خراسان شمالی", "خوزستان", "زنجان", "سمنان",
    "سیستان و بلوچستان", "فارس", "قزوین", "قم", "کردستان", "کرمان", "کرمانشاه", "کهگیلویه و بویراحمد",
    "گلستان", "گیلان", "لرستان", "مازندران", "مرکزی", "هرمزگان", "همدان", "یزد",
]
