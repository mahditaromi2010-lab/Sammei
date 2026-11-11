"""Image uploads. Every upload is decoded and re-encoded with Pillow, so only real
images are stored and any embedded payload or metadata is dropped."""
from __future__ import annotations

import secrets
from pathlib import Path

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 40_000_000
ALLOWED = {"JPEG", "PNG", "WEBP", "GIF", "MPO"}


class ImageError(ValueError):
    pass


def media_root() -> Path:
    root = Path(current_app.config["MEDIA_ROOT"])
    root.mkdir(parents=True, exist_ok=True)
    return root


def _open(file_storage) -> Image.Image:
    try:
        im = Image.open(file_storage.stream)
        if im.format not in ALLOWED:
            raise ImageError("فرمت تصویر پشتیبانی نمی‌شود (JPG، PNG یا WEBP).")
        im.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageError("فایل انتخاب‌شده تصویر معتبری نیست.") from exc
    im = ImageOps.exif_transpose(im)
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA" if "transparency" in im.info else "RGB")
    if im.mode == "RGBA":
        bg = Image.new("RGB", im.size, (255, 248, 241))
        bg.paste(im, mask=im.split()[3])
        im = bg
    return im


def _save(im: Image.Image, folder: str, name: str, size: int, quality: int) -> str:
    out = im.copy()
    out.thumbnail((size, size), Image.LANCZOS)
    rel = f"{folder}/{name}"
    path = media_root() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path, "WEBP", quality=quality, method=6)
    return rel


def save_product_image(file_storage) -> tuple[str, str]:
    im = _open(file_storage)
    token = secrets.token_hex(8)
    return (_save(im, "products", f"{token}.webp", 1400, 82),
            _save(im, "products", f"{token}-sm.webp", 600, 78))


def save_receipt(file_storage) -> str:
    im = _open(file_storage)
    return _save(im, "receipts", f"{secrets.token_hex(12)}.webp", 1800, 85)


def delete_media(*rels: str) -> None:
    root = media_root().resolve()
    for rel in rels:
        if not rel:
            continue
        path = (root / rel).resolve()
        if root in path.parents and path.is_file():
            path.unlink()
