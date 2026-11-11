"""ZarinPal v4 gateway (request -> redirect -> verify).

NOT ACTIVE by default. It is only offered at checkout when all of these hold:
  * ZARINPAL_MERCHANT_ID is set in the environment,
  * PUBLIC_BASE_URL is set (the callback must be an absolute https URL),
  * "gateway_enabled" is switched on in the admin panel.
Test the whole flow with ZARINPAL_SANDBOX=1 before switching to live.
"""
from __future__ import annotations

import json
import urllib.request

from flask import current_app

from .. import settings


class GatewayError(RuntimeError):
    pass


class ZarinPalProvider:
    code = "zarinpal"
    title = "پرداخت آنلاین (زرین‌پال)"
    description = "پرداخت با همه‌ی کارت‌های عضو شتاب"
    online = True

    def _base(self) -> str:
        sandbox = current_app.config.get("ZARINPAL_SANDBOX", True)
        return "https://sandbox.zarinpal.com" if sandbox else "https://payment.zarinpal.com"

    def is_enabled(self) -> bool:
        cfg = current_app.config
        return bool(cfg.get("ZARINPAL_MERCHANT_ID") and cfg.get("PUBLIC_BASE_URL")
                    and settings.get("gateway_enabled") == "1")

    def _post(self, path: str, payload: dict) -> dict:
        req = urllib.request.Request(
            self._base() + path, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:  # network errors, bad JSON
            raise GatewayError("ارتباط با درگاه برقرار نشد.") from exc

    def start(self, amount_toman: int, description: str, callback_url: str, mobile: str = "") -> tuple[str, str]:
        """Return (authority, redirect_url). Amount is sent in Rial."""
        data = self._post("/pg/v4/payment/request.json", {
            "merchant_id": current_app.config["ZARINPAL_MERCHANT_ID"],
            "amount": int(amount_toman) * 10,
            "currency": "IRR",
            "description": description[:250],
            "callback_url": callback_url,
            "metadata": {"mobile": mobile} if mobile else {},
        }).get("data") or {}
        if data.get("code") != 100 or not data.get("authority"):
            raise GatewayError("درگاه درخواست پرداخت را نپذیرفت.")
        authority = data["authority"]
        return authority, f"{self._base()}/pg/StartPay/{authority}"

    def verify(self, amount_toman: int, authority: str) -> str:
        """Return the bank reference id when the payment is confirmed (code 100 or 101)."""
        data = self._post("/pg/v4/payment/verify.json", {
            "merchant_id": current_app.config["ZARINPAL_MERCHANT_ID"],
            "amount": int(amount_toman) * 10,
            "authority": authority,
        }).get("data") or {}
        if data.get("code") in (100, 101) and data.get("ref_id"):
            return str(data["ref_id"])
        raise GatewayError("پرداخت تایید نشد.")
