from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from .services import has_any_perm


def _check(request, codes):
    if request.department is None or not has_any_perm(request.user, codes, request.department):
        raise PermissionDenied


class DepartmentPermissionMixin(LoginRequiredMixin):
    """Require one of `permission_required` (str or tuple) in the request's department."""

    permission_required: str | tuple[str, ...] = ()

    def get_permission_codes(self):
        codes = self.permission_required
        return (codes,) if isinstance(codes, str) else tuple(codes)

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        _check(request, self.get_permission_codes())
        return super().dispatch(request, *args, **kwargs)


def permission_required(*codes):
    """Function-view equivalent of DepartmentPermissionMixin. Passes if the user holds any of `codes`."""

    def decorator(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            _check(request, codes)
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
