from apps.institutions.models import AcademicSession

from .services import accessible_departments

SESSION_DEPARTMENT_KEY = "depthub_department_id"
SESSION_ACADEMIC_SESSION_KEY = "depthub_academic_session_id"


class DepartmentContextMiddleware:
    """Attach the user's working department and academic session to the request.

    The department is chosen from those the user can access (never trusted from the session alone).
    The academic session defaults to the institution's current session.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.department = None
        request.academic_session = None
        if request.user.is_authenticated:
            self._resolve(request)
        return self.get_response(request)

    def _resolve(self, request):
        departments = accessible_departments(request.user)
        wanted = request.session.get(SESSION_DEPARTMENT_KEY)
        department = departments.filter(pk=wanted).first() if wanted else None
        if department is None:
            department = departments.select_related("institution").order_by("name").first()
            if department is not None:
                request.session[SESSION_DEPARTMENT_KEY] = str(department.pk)
        request.department = department
        if department is None:
            return

        sessions = AcademicSession.objects.filter(institution_id=department.institution_id)
        wanted_session = request.session.get(SESSION_ACADEMIC_SESSION_KEY)
        session = sessions.filter(pk=wanted_session).first() if wanted_session else None
        if session is None:
            session = sessions.filter(is_current=True).first() or sessions.order_by("-starts_on").first()
        request.academic_session = session
