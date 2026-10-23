from apps.common.navigation import build_nav
from apps.institutions.models import AcademicSession

from .services import accessible_departments, permission_codes


def department_context(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    department = getattr(request, "department", None)
    perms = permission_codes(user, department)
    sessions = (
        AcademicSession.objects.filter(institution_id=department.institution_id)
        if department is not None
        else AcademicSession.objects.none()
    )
    return {
        "perms_codes": perms,
        "nav_sections": build_nav(request, perms),
        "current_department": department,
        "current_session": getattr(request, "academic_session", None),
        "available_departments": accessible_departments(user).order_by("name"),
        "available_sessions": sessions,
    }
