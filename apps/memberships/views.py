from django.db.models import DecimalField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render

from apps.access.mixins import permission_required
from apps.common.models import ZERO
from apps.finance.models import DuesAssessment, DuesBalance, Payment
from apps.finance.services.balances import with_balances
from apps.finance.views.common import paginate

from .models import DepartmentMembership

MONEY = DecimalField(max_digits=14, decimal_places=2)


def outstanding_subquery():
    rows = (
        DuesBalance.objects.filter(department_membership=OuterRef("pk"), balance__gt=0)
        .exclude(assessment_state=DuesAssessment.State.CANCELLED)
        .order_by()
        .values("department_membership")
        .annotate(total=Sum("balance"))
        .values("total")
    )
    return Coalesce(Subquery(rows, output_field=MONEY), Value(ZERO), output_field=MONEY)


@permission_required("members.roster.view", "members.roster.edit")
def roster(request):
    qs = (
        DepartmentMembership.objects.filter(
            department=request.department, academic_session=request.academic_session
        )
        .select_related("user__profile")
        .annotate(outstanding=outstanding_subquery())
    )
    level = request.GET.get("level", "")
    status = request.GET.get("status", "")
    owing = request.GET.get("owing", "")
    search = request.GET.get("q", "").strip()
    if level:
        qs = qs.filter(level_code=level)
    if status:
        qs = qs.filter(membership_status=status)
    if owing:
        qs = qs.filter(outstanding__gt=0)
    if search:
        qs = qs.filter(
            Q(user__email__icontains=search)
            | Q(user__profile__given_name__icontains=search)
            | Q(user__profile__family_name__icontains=search)
            | Q(user__profile__student_number__icontains=search)
        )
    qs = qs.order_by("level_code", "user__profile__family_name", "user__profile__given_name")
    page, query = paginate(request, qs)
    session_members = DepartmentMembership.objects.filter(
        department=request.department, academic_session=request.academic_session
    )
    levels = sorted({lv for lv in session_members.values_list("level_code", flat=True) if lv})
    return render(
        request,
        "memberships/roster.html",
        {
            "page": page,
            "query": query,
            "levels": levels,
            "statuses": DepartmentMembership.Status.choices,
            "filters": {"level": level, "status": status, "owing": owing, "q": search},
            "total_members": session_members.count(),
        },
    )


@permission_required("members.roster.view", "members.roster.edit")
def member_detail(request, pk):
    membership = get_object_or_404(
        DepartmentMembership.objects.select_related("user__profile", "academic_session"),
        pk=pk,
        department=request.department,
    )
    user = membership.user
    history = (
        DepartmentMembership.objects.filter(user=user, department=request.department)
        .select_related("academic_session")
        .order_by("-academic_session__starts_on")
    )
    assessments = with_balances(
        DuesAssessment.objects.filter(
            department_membership__user=user, department_membership__department=request.department
        )
        .select_related("dues_type", "department_membership__academic_session")
        .order_by("-department_membership__academic_session__starts_on", "due_date")
    )
    payments = (
        Payment.objects.filter(department=request.department, payer_membership__user=user)
        .select_related("receipt")
        .order_by("-initiated_at")[:50]
    )
    return render(
        request,
        "memberships/member_detail.html",
        {
            "membership": membership,
            "member": user,
            "history": history,
            "assessments": assessments,
            "payments": payments,
            "outstanding": sum((a.balance for a in assessments if a.balance > 0), ZERO),
        },
    )
