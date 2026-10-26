from rest_framework.permissions import BasePermission

from apps.access.services import has_any_perm


class HasDeptPermission(BasePermission):
    """Allow when the user holds any of the view's `required_perms` in the request's department.

    `required_perms` may be a tuple, or a dict mapping action names (or HTTP methods) to tuples.
    The department comes from the session context, never from the request body.
    """

    message = "You don't have permission for this in the current department."

    def _codes(self, request, view):
        required = getattr(view, "required_perms", ())
        if isinstance(required, dict):
            action = getattr(view, "action", None)
            return required.get(action) or required.get(request.method) or required.get("*", ())
        return required

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        codes = self._codes(request, view)
        if not codes:
            return True
        department = getattr(request._request, "department", None)
        return department is not None and has_any_perm(request.user, codes, department)
