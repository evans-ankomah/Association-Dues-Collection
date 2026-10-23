from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel
from apps.institutions.models import Department


class AuditEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise PermissionError("Audit events are append-only.")

    def delete(self):
        raise PermissionError("Audit events are append-only.")


class AuditEvent(TimeStampedModel):
    """Append-only record of an important action. Never updated or deleted."""

    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, null=True, blank=True, related_name="audit_events"
    )
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    action_key = models.CharField(max_length=100)
    entity_type = models.CharField(max_length=80)
    entity_id = models.UUIDField(null=True, blank=True)
    before_data = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    after_data = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    request_id = models.CharField(max_length=100, null=True, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)

    objects = AuditEventQuerySet.as_manager()

    class Meta:
        db_table = "audit_events"
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["department", "occurred_at"]),
            models.Index(fields=["entity_type", "entity_id"]),
        ]

    def __str__(self):
        return f"{self.occurred_at:%Y-%m-%d %H:%M} {self.action_key}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("Audit events are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Audit events are append-only.")
