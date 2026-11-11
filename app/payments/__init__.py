"""Payment methods.

Each method is a small provider class with the same shape, so adding a gateway
means adding one module and registering it here. Today only card-to-card is on;
ZarinPal is wired but stays disabled until a merchant ID is set and the flow has
been tested in sandbox.
"""
from __future__ import annotations

from .. import settings
from .card_to_card import CardToCardProvider
from .zarinpal import ZarinPalProvider

PROVIDERS = {p.code: p for p in (CardToCardProvider(), ZarinPalProvider())}


def available_methods() -> list:
    return [p for p in PROVIDERS.values() if p.is_enabled()]


def get_provider(code: str):
    provider = PROVIDERS.get(code)
    if provider is None or not provider.is_enabled():
        return None
    return provider


__all__ = ["available_methods", "get_provider", "PROVIDERS", "settings"]
