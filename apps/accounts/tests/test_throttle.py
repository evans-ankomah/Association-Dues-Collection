import logging

import pytest
from django.core.cache import cache

from apps.accounts import throttle
from apps.common.tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def attempt(client, email, password):
    return client.post("/accounts/login/", {"username": email, "password": password})


def test_lockout_after_repeated_failures_even_with_right_password(client, member):
    for _ in range(throttle.MAX_FAILURES):
        assert attempt(client, member.email, "wrong").status_code == 200
    response = attempt(client, member.email, TEST_PASSWORD)
    assert response.status_code == 200
    assert "Too many failed attempts" in response.content.decode()
    assert "_auth_user_id" not in client.session


def test_success_clears_the_counter(client, member):
    for _ in range(throttle.MAX_FAILURES - 1):
        attempt(client, member.email, "wrong")
    assert attempt(client, member.email, TEST_PASSWORD).status_code == 302
    client.logout()
    for _ in range(throttle.MAX_FAILURES - 1):
        attempt(client, member.email, "wrong")
    assert attempt(client, member.email, TEST_PASSWORD).status_code == 302


def test_lockout_is_per_email(client, member, make_user):
    for _ in range(throttle.MAX_FAILURES):
        attempt(client, "someone@example.test", "wrong")
    assert attempt(client, member.email, TEST_PASSWORD).status_code == 302


def test_log_lines_carry_request_id(client, caplog):
    from apps.audit.context import RequestIdLogFilter

    logger = logging.getLogger("depthub.test")
    handler_filter = RequestIdLogFilter()
    record = logger.makeRecord("depthub.test", logging.INFO, __file__, 1, "hello", (), None)
    assert handler_filter.filter(record) and record.request_id == "-"
