from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.access.mixins import permission_required
from apps.access.services import has_any_perm, has_perm
from apps.audit.services import record, snapshot
from apps.memberships.models import DepartmentMembership

from ..forms import AssessForm, CancelAssessmentForm, DuesTypeForm, WaiverRequestForm
from ..models import DuesAssessment, DuesType, WaiverRequest
from ..services import balances
from ..services import dues as dues_service
from ..services.errors import FinanceError
from .common import FINANCE_VIEWERS, paginate


def _dues_type(request, pk):
    return get_object_or_404(DuesType, pk=pk, department=request.department)


@permission_required(*FINANCE_VIEWERS)
def dues_type_list(request):
    types = DuesType.objects.filter(
        department=request.department, academic_session=request.academic_session
    ).order_by("due_date", "name")
    rows = [{"type": t, "totals": balances.totals(t.assessments.all())} for t in types]
    overall = balances.totals(DuesAssessment.objects.filter(dues_type__in=types))
    return render(
        request,
        "finance/dues_type_list.html",
        {
            "rows": rows,
            "overall": overall,
            "can_manage": has_perm(request.user, "dues.assessment.create", request.department),
        },
    )


@permission_required("dues.assessment.create")
def dues_type_create(request):
    if request.academic_session is None:
        messages.error(request, "Set up an academic session before creating dues.")
        return redirect("finance:dues_types")
    form = DuesTypeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        dues_type = form.save(commit=False)
        dues_type.department = request.department
        dues_type.academic_session = request.academic_session
        dues_type.currency = request.department.default_currency
        dues_type.created_by = request.user
        dues_type.save()
        record(
            "dues.type_created",
            dues_type,
            actor=request.user,
            department=request.department,
            after=snapshot(dues_type),
        )
        messages.success(request, f"Created {dues_type.name}. Next, choose who should pay it.")
        return redirect("finance:assess", pk=dues_type.pk)
    return render(request, "finance/dues_type_form.html", {"form": form, "dues_type": None})


@permission_required("dues.assessment.create")
def dues_type_edit(request, pk):
    dues_type = _dues_type(request, pk)
    has_assessments = dues_type.assessments.exists()
    form = DuesTypeForm(request.POST or None, instance=dues_type, has_assessments=has_assessments)
    if request.method == "POST" and form.is_valid():
        before = snapshot(DuesType.objects.get(pk=pk))
        form.save()
        record(
            "dues.type_updated",
            dues_type,
            actor=request.user,
            department=request.department,
            before=before,
            after=snapshot(dues_type),
        )
        messages.success(request, "Saved.")
        return redirect("finance:dues_type", pk=dues_type.pk)
    return render(request, "finance/dues_type_form.html", {"form": form, "dues_type": dues_type})


@permission_required(*FINANCE_VIEWERS)
def dues_type_detail(request, pk):
    dues_type = _dues_type(request, pk)
    qs = balances.with_balances(dues_type.assessments.select_related("department_membership__user__profile"))
    status = request.GET.get("status", "")
    level = request.GET.get("level", "")
    search = request.GET.get("q", "").strip()
    if status:
        qs = qs.filter(derived_status=status)
    if level:
        qs = qs.filter(department_membership__level_code=level)
    if search:
        qs = qs.filter(
            Q(department_membership__user__email__icontains=search)
            | Q(department_membership__user__profile__given_name__icontains=search)
            | Q(department_membership__user__profile__family_name__icontains=search)
            | Q(department_membership__user__profile__student_number__icontains=search)
        )
    qs = qs.order_by("department_membership__level_code", "department_membership__user__profile__family_name")
    page, query = paginate(request, qs)
    levels = (
        dues_type.assessments.values_list("department_membership__level_code", flat=True)
        .distinct()
        .order_by("department_membership__level_code")
    )
    return render(
        request,
        "finance/dues_type_detail.html",
        {
            "dues_type": dues_type,
            "totals": balances.totals(dues_type.assessments.all()),
            "page": page,
            "query": query,
            "levels": [lv for lv in levels if lv],
            "statuses": balances.DerivedStatus.LABELS,
            "filters": {"status": status, "level": level, "q": search},
            "can_manage": has_perm(request.user, "dues.assessment.create", request.department),
        },
    )


@permission_required("dues.assessment.create")
@require_POST
def dues_type_status(request, pk):
    dues_type = _dues_type(request, pk)
    try:
        dues_service.set_dues_type_status(dues_type, actor=request.user, status=request.POST.get("status"))
        messages.success(request, "Status updated.")
    except FinanceError as exc:
        messages.error(request, str(exc))
    return redirect("finance:dues_type", pk=pk)


@permission_required("dues.assessment.create")
def assess(request, pk):
    dues_type = _dues_type(request, pk)
    members = DepartmentMembership.objects.filter(
        department=request.department,
        academic_session=dues_type.academic_session,
        membership_status=DepartmentMembership.Status.ACTIVE,
    )
    level_choices = sorted({lv for lv in members.values_list("level_code", flat=True) if lv})
    programme_choices = sorted({p for p in members.values_list("programme_name", flat=True) if p})
    form = AssessForm(
        request.POST or None,
        level_choices=level_choices,
        programme_choices=programme_choices,
        initial={"amount": dues_type.default_amount, "due_date": dues_type.due_date},
    )
    preview = None
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        eligible = dues_service.eligible_memberships(dues_type, data["levels"], data["programmes"])
        if "confirm" in request.POST:
            try:
                created = dues_service.assess(
                    dues_type,
                    actor=request.user,
                    levels=data["levels"],
                    programmes=data["programmes"],
                    amount=data["amount"],
                    due_date=data["due_date"],
                )
            except FinanceError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, f"Assessed {created} member(s) for {dues_type.name}.")
                return redirect("finance:dues_type", pk=dues_type.pk)
        preview = {
            "count": eligible.count(),
            "total": data["amount"] * eligible.count(),
            "sample": eligible.select_related("user__profile")[:10],
        }
    return render(
        request,
        "finance/assess.html",
        {
            "dues_type": dues_type,
            "form": form,
            "preview": preview,
            "already": dues_type.assessments.exclude(assessment_state=DuesAssessment.State.CANCELLED).count(),
        },
    )


def _assessment_for(request, pk):
    assessment = get_object_or_404(
        DuesAssessment.objects.select_related(
            "dues_type", "department_membership__user__profile", "department_membership__academic_session"
        ),
        pk=pk,
        dues_type__department=request.department,
    )
    is_own = assessment.department_membership.user_id == request.user.pk
    if not is_own and not has_any_perm(
        request.user, FINANCE_VIEWERS + ("members.roster.view",), request.department
    ):
        raise PermissionDenied
    return assessment, is_own


@permission_required(*FINANCE_VIEWERS, "members.roster.view", "dues.own.view")
def assessment_detail(request, pk):
    assessment, is_own = _assessment_for(request, pk)
    row = balances.with_balances(DuesAssessment.objects.filter(pk=pk)).get()
    allocations = assessment.allocations.select_related("payment", "payment__receipt").order_by(
        "allocated_at"
    )
    can_manage = has_perm(request.user, "dues.assessment.create", request.department)
    pending_waiver = assessment.waiver_requests.filter(status=WaiverRequest.Status.PENDING).first()
    return render(
        request,
        "finance/assessment_detail.html",
        {
            "assessment": assessment,
            "row": row,
            "allocations": allocations,
            "waivers": assessment.waiver_requests.select_related("requested_by", "decided_by"),
            "pending_waiver": pending_waiver,
            "is_own": is_own,
            "can_manage": can_manage,
            "can_request_waiver": (is_own or can_manage)
            and assessment.assessment_state == DuesAssessment.State.ACTIVE
            and row.balance > 0
            and pending_waiver is None,
            "waiver_form": WaiverRequestForm(initial={"amount": row.balance}),
            "cancel_form": CancelAssessmentForm(),
        },
    )


@permission_required("dues.assessment.create", "dues.own.view")
@require_POST
def request_waiver(request, pk):
    assessment, _is_own = _assessment_for(request, pk)
    form = WaiverRequestForm(request.POST)
    if form.is_valid():
        try:
            dues_service.request_waiver(
                assessment,
                actor=request.user,
                amount=form.cleaned_data["amount"],
                reason=form.cleaned_data["reason"],
            )
            messages.success(request, "Waiver requested. The HoD or faculty adviser will review it.")
        except FinanceError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, "Check the waiver amount and reason.")
    return redirect("finance:assessment", pk=pk)


@permission_required("dues.assessment.create")
@require_POST
def cancel_assessment(request, pk):
    assessment, _ = _assessment_for(request, pk)
    form = CancelAssessmentForm(request.POST)
    if form.is_valid():
        try:
            dues_service.cancel_assessment(assessment, actor=request.user, reason=form.cleaned_data["reason"])
            messages.success(request, "Assessment cancelled.")
        except FinanceError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, "Give a reason for cancelling.")
    return redirect("finance:assessment", pk=pk)
