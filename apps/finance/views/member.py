from itertools import groupby

from django.shortcuts import render

from apps.access.mixins import permission_required

from ..models import DuesAssessment
from ..services import balances


@permission_required("dues.own.view")
def my_dues(request):
    qs = balances.with_balances(
        DuesAssessment.objects.filter(
            department_membership__user=request.user,
            department_membership__department=request.department,
        )
        .exclude(assessment_state=DuesAssessment.State.CANCELLED)
        .select_related("dues_type", "department_membership__academic_session")
        .order_by("-department_membership__academic_session__starts_on", "due_date", "dues_type__name")
    )
    assessments = list(qs)
    sessions = [
        {"session": session, "items": list(items)}
        for session, items in groupby(assessments, key=lambda a: a.department_membership.academic_session)
    ]
    outstanding = sum((a.balance for a in assessments if a.balance > 0), balances.ZERO)
    return render(
        request,
        "finance/my_dues.html",
        {
            "sessions": sessions,
            "outstanding": outstanding,
            "overdue": [a for a in assessments if a.derived_status == balances.DerivedStatus.OVERDUE],
        },
    )
