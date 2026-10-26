"""Slow down password guessing: too many failed sign-ins for one email, or from one address, locks
that key out for a while. Uses the Django cache, so production must use a shared cache (Redis)."""

import hashlib

from django.core.cache import cache

MAX_FAILURES = 5
PER_IP_MAX_FAILURES = 30
WINDOW_SECONDS = 15 * 60


def _key(kind, value):
    digest = hashlib.sha256(value.encode()).hexdigest()[:32]
    return f"login-fail:{kind}:{digest}"


def client_ip(request):
    # REMOTE_ADDR is set by the app server; behind a proxy, configure it to pass the real address.
    return request.META.get("REMOTE_ADDR", "") if request is not None else ""


def is_locked(email, ip):
    return (cache.get(_key("email", email), 0) >= MAX_FAILURES) or (
        bool(ip) and cache.get(_key("ip", ip), 0) >= PER_IP_MAX_FAILURES
    )


def record_failure(email, ip):
    for kind, value in (("email", email), ("ip", ip)):
        if not value:
            continue
        key = _key(kind, value)
        if cache.add(key, 1, WINDOW_SECONDS):
            continue
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, WINDOW_SECONDS)


def clear(email):
    cache.delete(_key("email", email))
