from django.core.exceptions import PermissionDenied

from apps.access.services import has_perm


class FinanceError(Exception):
    """A business-rule violation with a message safe to show to the user."""


def require_perm(actor, code, department):
    """Services re-check permissions so they're safe to call from views, the API or tasks."""
    if not has_perm(actor, code, department):
        raise PermissionDenied(f"Missing permission {code}.")
