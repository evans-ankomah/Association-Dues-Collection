from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.access.mixins import permission_required

from ..forms import DecisionForm
from ..models import DuesAssessment, WaiverRequest
from ..services import balances
from ..services import dues as dues_service
from ..services.errors import FinanceError
from .common import paginate


@permission_required("dues.waiver.approve", "dues.assessment.create")
def waiver_list(request):
    base = WaiverRequest.objects.filter(
        dues_assessment__dues_type__department=request.department
    ).select_related(
        "dues_assessment__dues_type",
        "dues_assessment__department_membership__user__profile",
        "requested_by__profile",
        "decided_by__profile",
    )
    status = request.GET.get("status", WaiverRequest.Status.PENDING)
    qs = base.filter(status=status) if status else base
    page, query = paginate(request, qs.order_by("-created_at"))
    assessment_ids = [w.dues_assessment_id for w in page]
    balance_by_id = dict(
        balances.with_balances(DuesAssessment.objects.filter(pk__in=assessment_ids)).values_list(
            "pk", "balance"
        )
    )
    for waiver in page:
        waiver.current_balance = balance_by_id.get(waiver.dues_assessment_id)
    return render(
        request,
        "finance/waiver_list.html",
        {
            "page": page,
            "query": query,
            "status": status,
            "statuses": WaiverRequest.Status.choices,
            "pending_count": base.filter(status=WaiverRequest.Status.PENDING).count(),
            "form": DecisionForm(),
        },
    )


@permission_required("dues.waiver.approve")
@require_POST
def decide_waiver(request, pk):
    waiver = get_object_or_404(
        WaiverRequest, pk=pk, dues_assessment__dues_type__department=request.department
    )
    form = DecisionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Choose approve or reject.")
        return redirect("finance:waivers")
    approve = form.cleaned_data["decision"] == "approve"
    try:
        dues_service.decide_waiver(
            waiver, actor=request.user, approve=approve, note=form.cleaned_data["note"]
        )
        messages.success(request, "Waiver approved." if approve else "Waiver rejected.")
    except FinanceError as exc:
        messages.error(request, str(exc))
    return redirect("finance:waivers")
