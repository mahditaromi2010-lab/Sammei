"""Command line: flask --app wsgi seed | create-admin | expire-orders"""
from __future__ import annotations

import getpass
import os
import shutil
from pathlib import Path

import click
from flask import current_app

from .extensions import db
from .models import AdminUser, Category, Product, ProductImage

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"


def seed_catalog(force: bool = False) -> int:
    from seed.catalog import CATEGORIES, CROCHET_MATERIAL, PAINT_MATERIAL, PAINTINGS, PRODUCTS

    if Product.query.count() and not force:
        return 0
    media = Path(current_app.config["MEDIA_ROOT"]) / "products"
    media.mkdir(parents=True, exist_ok=True)
    cats = {}
    for slug, name, desc, sort in CATEGORIES:
        c = Category.query.filter_by(slug=slug).first() or Category(slug=slug)
        c.name, c.description, c.sort, c.is_active = name, desc, sort, True
        db.session.add(c)
        cats[slug] = c
    db.session.flush()

    def add_images(p: Product, numbers):
        for n, num in enumerate(numbers):
            for suffix in ("", "-sm"):
                src = SEED_DIR / "images" / f"p{num}{suffix}.webp"
                if src.exists():
                    shutil.copyfile(src, media / src.name)
            p.images.append(ProductImage(path=f"products/p{num}.webp", path_sm=f"products/p{num}-sm.webp",
                                         alt=p.title, sort=n))

    created = 0
    for i, (slug, title, cat, price, images, short, size, featured, stock) in enumerate(PRODUCTS):
        if Product.query.filter_by(slug=slug).first():
            continue
        p = Product(slug=slug, title=title, category=cats[cat], kind="crochet", price=price, short=short, size=size,
                    is_featured=featured, stock=stock, material=CROCHET_MATERIAL, sort=i, making_days=7,
                    made_to_order=False, care="با دست و آب ولرم بشویید؛ در سایه خشک شود. برای کودکان زیر ۳ سال مناسب نیست.",
                    description=f"{short}. این عروسک به‌صورت کامل با دست و قلاب بافته شده و داخلش با الیاف نرم پر شده است. "
                                "اگر موجودی تمام شده باشد، می‌توانی سفارش ساخت بدهی.")
        add_images(p, images)
        db.session.add(p)
        created += 1
    for i, (slug, title, image, price, size, featured) in enumerate(PAINTINGS):
        if Product.query.filter_by(slug=slug).first():
            continue
        p = Product(slug=slug, title=title, category=cats["paintings"], kind="painting", price=price,
                    short=f"تابلوی اکریلیک اصل، {size} سانتی‌متر", size=f"{size} سانتی‌متر", is_featured=featured,
                    stock=1, material=PAINT_MATERIAL, sort=100 + i,
                    care="دور از نور مستقیم آفتاب و رطوبت نگه دارید؛ با دستمال خشک گردگیری شود.",
                    description="یک نقاشی تک و اصل با امضای هنرمند. هر تابلو فقط یک نسخه دارد و پس از فروش، "
                                "از فروشگاه برداشته می‌شود.")
        add_images(p, [image])
        db.session.add(p)
        created += 1
    db.session.commit()
    return created


def register_cli(app):
    @app.cli.command("seed")
    @click.option("--force", is_flag=True, help="Add missing seed products even if the shop already has products.")
    def seed_cmd(force):
        """Create categories and products from seed/ (safe to run twice)."""
        n = seed_catalog(force)
        click.echo(f"{n} products created.")

    @app.cli.command("create-admin")
    @click.argument("username")
    def create_admin(username):
        """Create an admin, or reset their password. Reads ADMIN_PASSWORD or prompts."""
        password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Password (min 10 chars): ")
        if len(password) < 10:
            raise click.ClickException("Password must be at least 10 characters.")
        user = AdminUser.query.filter_by(username=username).first() or AdminUser(username=username)
        user.set_password(password)
        user.is_active = True
        user.failed_logins = 0
        user.locked_until = None
        db.session.add(user)
        db.session.commit()
        click.echo(f"Admin '{username}' is ready.")

    @app.cli.command("expire-orders")
    def expire_orders():
        """Cancel unpaid card-to-card orders older than ORDER_HOLD_HOURS (run from cron)."""
        from .orders import expire_unpaid
        click.echo(f"{expire_unpaid(current_app.config['ORDER_HOLD_HOURS'])} orders cancelled.")
