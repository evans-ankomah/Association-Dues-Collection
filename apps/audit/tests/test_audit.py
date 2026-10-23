import pytest

from apps.audit.models import AuditEvent
from apps.audit.services import record

pytestmark = pytest.mark.django_db


def test_record_captures_request_id(member, login):
    client = login(member)
    response = client.get("/", HTTP_X_REQUEST_ID="abc-123")
    assert response["X-Request-ID"] == "abc-123"
    event = AuditEvent.objects.filter(action_key="auth.login").first()
    assert event is not None


def test_malformed_request_id_is_replaced(client, db):
    response = client.get("/healthz/", HTTP_X_REQUEST_ID="bad id <script>")
    assert response["X-Request-ID"] != "bad id <script>"
    assert len(response["X-Request-ID"]) == 32


def test_audit_events_are_append_only(member):
    event = record("test.action", member, actor=member)
    event.action_key = "changed"
    with pytest.raises(PermissionError):
        event.save()
    with pytest.raises(PermissionError):
        event.delete()
    with pytest.raises(PermissionError):
        AuditEvent.objects.all().delete()
    with pytest.raises(PermissionError):
        AuditEvent.objects.update(action_key="x")
