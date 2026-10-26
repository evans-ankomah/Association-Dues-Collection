from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.access.mixins import permission_required
from apps.access.services import has_any_perm, has_perm

from ..models import Payment, PaymentAdjustment
from ..services import adjustments as svc
from ..services.errors import FinanceError
from .common import paginate

VIEWERS = (
    "finance.adjustment.approve",
    "finance.payment.verify",
    "finance.payment.record",
    "finance.reconciliation.view",
    "finance.report.export",
)


@permission_required(*VIEWERS)
def adjustment_list(request):
    status = request.GET.get("status", PaymentAdjustment.Status.PENDING_APPROVAL)
    qs = PaymentAdjustment.objects.filter(payment__department=request.department).select_related(
        "payment__payer_membership__user__profile", "requested_by__profile", "approved_by__profile"
    )
    if status:
        qs = qs.filter(adjustment_status=status)
    page, query = paginate(request, qs.order_by("-created_at"))
    return render(
        request,
        "finance/adjustment_list.html",
        {"page": page, "query": query, "status": status, "statuses": PaymentAdjustment.Status.choices},
    )


def _reversals_from(post, allocations):
    plan = []
    for allocation in allocations:
        raw = (post.get(f"rev_{allocation.pk}") or "").strip()
        if not raw:
            continue
        try:
            value = Decimal(raw)
        except InvalidOperation as exc:
            raise FinanceError("Enter amounts as numbers.") from exc
        if value > 0:
            plan.append((allocation, value))
    return plan


@permission_required(*svc.REQUESTERS)
def request_adjustment(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related("payer_membership__user__profile"),
        pk=pk,
        department=request.department,
    )
    allocations = svc.allocations_with_reversible(payment)
    if request.method == "POST":
        try:
            amount = Decimal(request.POST.get("amount") or "0")
            adjustment = svc.request_adjustment(
                payment,
                actor=request.user,
                adjustment_type=request.POST.get("adjustment_type") or PaymentAdjustment.Type.REFUND,
                amount=amount,
                reason=request.POST.get("reason", ""),
                reversals=_reversals_from(request.POST, allocations),
            )
        except (FinanceError, InvalidOperation) as exc:
            messages.error(request, str(exc) if isinstance(exc, FinanceError) else "Enter a valid amount.")
        else:
            messages.success(request, "Sent to the HoD or adviser for approval.")
            return redirect("finance:adjustment", pk=adjustment.pk)
    return render(
        request,
        "finance/adjustment_request.html",
        {
            "payment": payment,
            "allocations": allocations,
            "refundable": svc.refundable_amount(payment),
            "unallocated": max(svc.unallocated_refundable(payment), Decimal("0")),
            "types": PaymentAdjustment.Type.choices,
            "posted": request.POST,
        },
    )


@permission_required(*VIEWERS)
def adjustment_detail(request, pk):
    adjustment = get_object_or_404(
        PaymentAdjustment.objects.select_related(
            "payment__payer_membership__user__profile", "requested_by__profile", "approved_by__profile"
        ),
        pk=pk,
        payment__department=request.department,
    )
    is_pending = adjustment.adjustment_status == PaymentAdjustment.Status.PENDING_APPROVAL
    return render(
        request,
        "finance/adjustment_detail.html",
        {
            "adjustment": adjustment,
            "reversals": adjustment.allocation_adjustments.select_related(
                "payment_allocation__dues_assessment__dues_type"
            ),
            "can_decide": is_pending
            and has_perm(request.user, "finance.adjustment.approve", request.department)
            and adjustment.requested_by_id != request.user.pk,
            "can_process": adjustment.adjustment_status == PaymentAdjustment.Status.APPROVED
            and has_any_perm(request.user, svc.REQUESTERS, request.department)
            and adjustment.approved_by_id != request.user.pk,
        },
    )


@permission_required("finance.adjustment.approve")
@require_POST
def decide_adjustment(request, pk):
    adjustment = get_object_or_404(PaymentAdjustment, pk=pk, payment__department=request.department)
    approve = request.POST.get("decision") == "approve"
    try:
        svc.decide_adjustment(
            adjustment, actor=request.user, approve=approve, note=request.POST.get("note", "")
        )
        messages.success(
            request, "Approved. A finance officer will now return the money." if approve else "Rejected."
        )
    except FinanceError as exc:
        messages.error(request, str(exc))
    return redirect("finance:adjustment", pk=pk)


@permission_required(*svc.REQUESTERS)
@require_POST
def process_adjustment(request, pk):
    adjustment = get_object_or_404(PaymentAdjustment, pk=pk, payment__department=request.department)
    try:
        svc.process_adjustment(
            adjustment, actor=request.user, provider_reference=request.POST.get("provider_reference", "")
        )
        messages.success(request, "Refund recorded. The member's balance has been updated.")
    except FinanceError as exc:
        messages.error(request, str(exc))
    return redirect("finance:adjustment", pk=pk)
