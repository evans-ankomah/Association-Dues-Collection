from django.forms.models import model_to_dict

from .context import request_id_var
from .models import AuditEvent

# Never written into audit snapshots.
_REDACTED_FIELDS = {"password", "phone_number", "safe_metadata"}


def snapshot(instance, fields=None):
    """A JSON-safe dict of a model instance's fields, without secrets or contact details."""
    if instance is None:
        return None
    data = model_to_dict(instance, fields=fields)
    return {
        k: (str(v) if v is not None and not isinstance(v, bool | int | str) else v)
        for k, v in data.items()
        if k not in _REDACTED_FIELDS
    }


def record(action_key, entity, *, actor=None, department=None, before=None, after=None, entity_type=None):
    """Append an audit event. `entity` is a model instance (or None with an explicit entity_type)."""
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None
    return AuditEvent.objects.create(
        department=department,
        actor_user=actor,
        action_key=action_key,
        entity_type=entity_type or (entity._meta.db_table if entity is not None else "unknown"),
        entity_id=getattr(entity, "pk", None),
        before_data=before,
        after_data=after,
        request_id=request_id_var.get(),
    )
