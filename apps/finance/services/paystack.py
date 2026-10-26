"""Paystack API client and webhook signature check. No business logic here."""

import hashlib
import hmac
import logging
from decimal import ROUND_HALF_UP, Decimal

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 15


class PaystackError(Exception):
    """The Paystack API could not be reached or refused the request."""


def is_configured():
    return bool(settings.PAYSTACK_SECRET_KEY)


def to_minor_units(amount: Decimal) -> int:
    """GHS 150.00 -> 15000 pesewas, exactly (no floats)."""
    return int((Decimal(amount) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def from_minor_units(value: int) -> Decimal:
    return (Decimal(int(value)) / 100).quantize(Decimal("0.01"))


def _headers():
    return {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }


def _call(method, path, **kwargs):
    if not is_configured():
        raise PaystackError("Online payments are not configured.")
    url = f"{settings.PAYSTACK_BASE_URL.rstrip('/')}{path}"
    try:
        response = requests.request(method, url, headers=_headers(), timeout=TIMEOUT_SECONDS, **kwargs)
    except requests.RequestException as exc:
        logger.warning("Paystack request failed: %s %s (%s)", method, path, exc.__class__.__name__)
        raise PaystackError("Couldn't reach Paystack. Please try again.") from exc
    try:
        body = response.json()
    except ValueError as exc:
        raise PaystackError("Paystack sent an unreadable response.") from exc
    if response.status_code >= 400 or not body.get("status"):
        logger.warning("Paystack refused %s %s: HTTP %s", method, path, response.status_code)
        raise PaystackError(body.get("message") or "Paystack refused the request.")
    return body["data"]


def initialize(*, email, amount, currency, reference, callback_url, metadata=None):
    """Start a transaction. Returns Paystack's data dict including authorization_url."""
    return _call(
        "POST",
        "/transaction/initialize",
        json={
            "email": email,
            "amount": to_minor_units(amount),
            "currency": currency,
            "reference": reference,
            "callback_url": callback_url,
            "channels": ["mobile_money", "card", "bank"],
            "metadata": metadata or {},
        },
    )


def verify(reference):
    """Look up a transaction by our reference. Returns Paystack's data dict."""
    return _call("GET", f"/transaction/verify/{requests.utils.quote(reference, safe='')}")


def signature_is_valid(raw_body: bytes, signature: str | None) -> bool:
    """Paystack signs the raw request body with HMAC-SHA512 using the secret key."""
    if not signature or not is_configured():
        return False
    expected = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)
