from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.institutions.models import AcademicSession

from .middleware import SESSION_ACADEMIC_SESSION_KEY, SESSION_DEPARTMENT_KEY
from .services import accessible_departments


def _back(request):
    target = request.POST.get("next") or request.META.get("HTTP_REFERER") or "/"
    if not url_has_allowed_host_and_scheme(target, {request.get_host()}, require_https=request.is_secure()):
        target = "/"
    return redirect(target)


@login_required
@require_POST
def switch_context(request):
    department_id = request.POST.get("department")
    if department_id and accessible_departments(request.user).filter(pk=department_id).exists():
        if request.session.get(SESSION_DEPARTMENT_KEY) != department_id:
            request.session.pop(SESSION_ACADEMIC_SESSION_KEY, None)
        request.session[SESSION_DEPARTMENT_KEY] = department_id

    session_id = request.POST.get("academic_session")
    if session_id and request.department is not None:
        valid = AcademicSession.objects.filter(
            pk=session_id, institution_id=request.department.institution_id
        )
        if valid.exists():
            request.session[SESSION_ACADEMIC_SESSION_KEY] = session_id
    return _back(request)
