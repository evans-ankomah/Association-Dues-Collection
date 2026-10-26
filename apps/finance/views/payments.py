from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.access.mixins import permission_required
from apps.access.services import has_any_perm, has_perm
from apps.audit.models import AuditEvent
from apps.memberships.models import DepartmentMembership

from ..models import Payment, Receipt
from ..payment_forms import PaymentClaimForm, RecordPaymentForm, RejectPaymentForm, parse_allocations
from ..services import payments as svc
from ..services.errors import FinanceError
from ..services.receipt_pdf import render_receipt_pdf
from .common import FINANCE_VIEWERS, paginate


def _payment_for(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related(
            "payer_membership__user__profile", "recorded_by__profile", "verified_by__profile"
        ),
        pk=pk,
        department=request.department,
    )
    is_payer = payment.payer_membership is not None and payment.payer_membership.user_id == request.user.pk
    if not is_payer and not has_any_perm(request.user, FINANCE_VIEWERS, request.department):
        raise PermissionDenied
    return payment, is_payer


@permission_required(*FINANCE_VIEWERS)
def payment_list(request):
    qs = Payment.objects.filter(department=request.department).select_related(
        "payer_membership__user__profile", "receipt"
    )
    status = request.GET.get("status", "")
    method = request.GET.get("method", "")
    search = request.GET.get("q", "").strip()
    if status:
        qs = qs.filter(payment_status=status)
    if method:
        qs = qs.filter(payment_method=method)
    if search:
        qs = qs.filter(
            Q(payer_membership__user__email__icontains=search)
            | Q(payer_membership__user__profile__family_name__icontains=search)
            | Q(payer_membership__user__profile__given_name__icontains=search)
            | Q(payer_membership__user__profile__student_number__icontains=search)
            | Q(external_reference__icontains=search)
            | Q(provider_reference__icontains=search)
            | Q(receipt__receipt_number__icontains=search)
        )
    page, query = paginate(request, qs.order_by("-initiated_at"))
    return render(
        request,
        "finance/payment_list.html",
        {
            "page": page,
            "query": query,
            "filters": {"status": status, "method": method, "q": search},
            "statuses": Payment.Status.choices,
            "methods": Payment.Method.choices,
            "pending_count": Payment.objects.filter(
                department=request.department, payment_status=Payment.Status.PENDING
            ).count(),
            "can_record": has_perm(request.user, "finance.payment.record", request.department),
        },
    )


@permission_required("finance.payment.record")
def member_search(request):
    """HTMX: members matching a name, email or student number, for the record-payment form."""
    term = request.GET.get("q", "").strip()
    results = []
    if len(term) >= 2:
        results = (
            DepartmentMembership.objects.filter(department=request.department)
            .filter(
                Q(user__email__icontains=term)
                | Q(user__profile__student_number__icontains=term)
                | Q(user__profile__family_name__icontains=term)
                | Q(user__profile__given_name__icontains=term)
            )
            .select_related("user__profile", "academic_session")
            .order_by("user_id", "-academic_session__starts_on")
            .distinct("user_id")[:8]
        )
    return render(request, "finance/partials/member_results.html", {"results": results, "term": term})


@permission_required("finance.payment.record")
def record_payment(request):
    form = RecordPaymentForm(request.POST or None, department=request.department)
    selected = None
    if request.method == "POST":
        if form.is_valid():
            data = form.cleaned_data
            try:
                payment = svc.record_offline_payment(
                    data["membership"],
                    actor=request.user,
                    method=data["method"],
                    amount=data["amount"],
                    reference=data["reference"],
                    notes=data["notes"],
                    provider_name=form.provider_name(),
                )
            except FinanceError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request, "Payment recorded. The Treasurer will verify it and issue the receipt."
                )
                return redirect("finance:payment", pk=payment.pk)
        selected = form.cleaned_data.get("membership") if hasattr(form, "cleaned_data") else None
    return render(request, "finance/record_payment.html", {"form": form, "selected": selected})


@permission_required(*FINANCE_VIEWERS, "dues.own.view", "finance.receipt.view")
def payment_detail(request, pk):
    payment, is_payer = _payment_for(request, pk)
    allocations = payment.allocations.select_related(
        "dues_assessment__dues_type", "dues_assessment__department_membership__academic_session"
    )
    can_verify = (
        payment.payment_status == Payment.Status.PENDING
        and payment.payment_method != Payment.Method.PROVIDER
        and has_perm(request.user, "finance.payment.verify", request.department)
        and payment.recorded_by_id != request.user.pk
        and not is_payer
    )
    context = {
        "payment": payment,
        "is_payer": is_payer,
        "allocations": allocations,
        "receipt": Receipt.objects.filter(payment=payment).first(),
        "unallocated": svc.unallocated_amount(payment) if payment.is_confirmed else None,
        "can_verify": can_verify,
        "can_cancel": payment.payment_status == Payment.Status.PENDING
        and payment.recorded_by_id == request.user.pk,
        "can_refund": payment.payment_status in (Payment.Status.CONFIRMED, Payment.Status.PARTIALLY_REFUNDED)
        and has_any_perm(
            request.user, ("finance.payment.verify", "finance.payment.record"), request.department
        ),
        "adjustments": payment.adjustments.order_by("-created_at"),
        "reject_form": RejectPaymentForm(),
        "history": AuditEvent.objects.filter(entity_type="payments", entity_id=payment.pk)
        .select_related("actor_user__profile")
        .order_by("occurred_at")
        if not is_payer or has_any_perm(request.user, FINANCE_VIEWERS, request.department)
        else [],
    }
    if can_verify and payment.payer_membership_id:
        suggestion = dict((a.pk, amt) for a, amt in svc.suggest_allocations(payment))
        outstanding = list(svc.outstanding_assessments(payment.payer_membership))
        for a in outstanding:
            a.suggested = suggestion.get(a.pk, Decimal("0.00"))
        context["outstanding"] = outstanding
        context["suggested_total"] = sum(suggestion.values(), Decimal("0"))
    return render(request, "finance/payment_detail.html", context)


@permission_required("finance.payment.verify")
@require_POST
def verify_payment(request, pk):
    payment, _ = _payment_for(request, pk)
    outstanding = svc.outstanding_assessments(payment.payer_membership) if payment.payer_membership_id else []
    plan, errors = parse_allocations(request.POST, outstanding)
    if errors:
        for error in errors:
            messages.error(request, error)
        return redirect("finance:payment", pk=pk)
    try:
        receipt = svc.verify_payment(payment, actor=request.user, allocations=plan)
    except FinanceError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Payment confirmed. Receipt {receipt.receipt_number} issued.")
    return redirect("finance:payment", pk=pk)


@permission_required("finance.payment.verify")
@require_POST
def reject_payment(request, pk):
    payment, _ = _payment_for(request, pk)
    form = RejectPaymentForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Say why the payment is being rejected.")
        return redirect("finance:payment", pk=pk)
    try:
        svc.reject_payment(payment, actor=request.user, reason=form.cleaned_data["reason"])
        messages.success(request, "Payment marked as failed.")
    except FinanceError as exc:
        messages.error(request, str(exc))
    return redirect("finance:payment", pk=pk)


@require_POST
@permission_required(*FINANCE_VIEWERS, "finance.payment.initiate")
def cancel_payment(request, pk):
    payment, is_payer = _payment_for(request, pk)
    try:
        svc.cancel_payment(payment, actor=request.user)
        messages.success(request, "Payment withdrawn.")
    except FinanceError as exc:
        messages.error(request, str(exc))
    return redirect("finance:my_payments" if is_payer else "finance:payments")


def _current_membership(request):
    memberships = DepartmentMembership.objects.filter(user=request.user, department=request.department)
    if request.academic_session is not None:
        current = memberships.filter(academic_session=request.academic_session).first()
        if current:
            return current
    return memberships.order_by("-academic_session__starts_on").first()


@permission_required("dues.own.view", "finance.receipt.view")
def my_payments(request):
    payments = (
        Payment.objects.filter(department=request.department, payer_membership__user=request.user)
        .select_related("receipt")
        .order_by("-initiated_at")
    )
    membership = _current_membership(request)
    form = PaymentClaimForm(request.POST or None)
    if request.method == "POST":
        if not has_perm(request.user, "finance.payment.initiate", request.department) or membership is None:
            raise PermissionDenied
        if form.is_valid():
            data = form.cleaned_data
            try:
                svc.submit_payment_claim(
                    membership,
                    actor=request.user,
                    method=data["method"],
                    amount=data["amount"],
                    reference=data["reference"],
                    notes=data["notes"],
                    provider_name=form.provider_name(),
                )
            except FinanceError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request, "Thanks. The Treasurer will check the transaction and send your receipt."
                )
                return redirect("finance:my_payments")
    outstanding = list(svc.outstanding_assessments(membership)) if membership else []
    return render(
        request,
        "finance/my_payments.html",
        {
            "payments": payments,
            "form": form,
            "can_report": membership is not None
            and has_perm(request.user, "finance.payment.initiate", request.department),
            "outstanding_total": sum((a.balance for a in outstanding), Decimal("0")),
        },
    )


def _receipt_for(request, pk):
    receipt = get_object_or_404(
        Receipt.objects.select_related("payment__payer_membership__user__profile", "payment__department"),
        pk=pk,
        payment__department=request.department,
    )
    payment = receipt.payment
    is_payer = payment.payer_membership is not None and payment.payer_membership.user_id == request.user.pk
    if not is_payer and not has_any_perm(request.user, FINANCE_VIEWERS, request.department):
        raise PermissionDenied
    return receipt


@permission_required(*FINANCE_VIEWERS, "finance.receipt.view")
def receipt_detail(request, pk):
    receipt = _receipt_for(request, pk)
    allocations = receipt.payment.allocations.select_related(
        "dues_assessment__dues_type", "dues_assessment__department_membership__academic_session"
    )
    return render(request, "finance/receipt.html", {"receipt": receipt, "allocations": allocations})


@permission_required(*FINANCE_VIEWERS, "finance.receipt.view")
def receipt_pdf(request, pk):
    receipt = _receipt_for(request, pk)
    pdf = render_receipt_pdf(receipt, site_name=settings.SITE_NAME)
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{receipt.receipt_number}.pdf"'
    return response
