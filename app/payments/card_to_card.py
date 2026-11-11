from __future__ import annotations

from .. import settings


class CardToCardProvider:
    """Manual bank transfer: the customer pays, uploads a receipt, an admin approves it."""

    code = "card_to_card"
    title = "کارت‌به‌کارت"
    description = "واریز به کارت فروشگاه و ثبت رسید؛ تایید توسط فروشگاه"
    online = False

    def is_enabled(self) -> bool:
        return settings.get("card_to_card_enabled", "1") == "1" and bool(settings.get("card_number"))

    def account(self) -> dict:
        return {
            "card_number": settings.get("card_number"),
            "card_holder": settings.get("card_holder"),
            "card_bank": settings.get("card_bank"),
            "sheba": settings.get("sheba"),
            "instructions": settings.get("card_instructions"),
        }
