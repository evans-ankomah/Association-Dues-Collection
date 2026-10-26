import logging

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.access.mixins import permission_required

from ..models import Payment
from ..services import online, paystack
from ..services.errors import FinanceError
from ..services.payments import outstanding_assessments
from .payments import _current_membership

logger = logging.getLogger(__name__)


@permission_required("finance.payment.initiate")
def pay_online(request):
    membership = _current_membership(request)
    outstanding = list(outstanding_assessments(membership)) if membership else []
    if request.method == "POST":
        try:
            _payment, checkout_url = online.start_online_payment(
                membership,
                actor=request.user,
                assessment_ids=request.POST.getlist("assessment"),
                callback_url=request.build_absolute_uri(reverse("finance:paystack_callback")),
            )
        except FinanceError as exc:
            messages.error(request, str(exc))
        else:
            return redirect(checkout_url)
    return render(
        request,
        "finance/pay_online.html",
        {"outstanding": outstanding, "configured": paystack.is_configured()},
    )


def _own_online_payment(request, reference):
    return get_object_or_404(
        Payment,
        provider_name=online.PROVIDER,
        provider_reference=reference,
        payer_membership__user=request.user,
    )


@permission_required("finance.payment.initiate")
def paystack_callback(request):
    """Paystack sends the payer back here. We check with Paystack ourselves before showing success."""
    reference = request.GET.get("reference") or request.GET.get("trxref") or ""
    payment = _own_online_payment(request, reference)
    if payment.payment_status == Payment.Status.PENDING:
        try:
            online.verify_with_provider(payment)
        except paystack.PaystackError:
            logger.info("Verify call failed for %s; waiting for webhook.", reference)
        payment.refresh_from_db()
    return render(request, "finance/online_status.html", {"payment": payment})


@permission_required("finance.payment.initiate")
def online_status(request, reference):
    """HTMX poll while a payment is still pending."""
    payment = _own_online_payment(request, reference)
    return render(request, "finance/partials/online_status.html", {"payment": payment})


@csrf_exempt
@require_POST
def paystack_webhook(request):
    status = online.handle_webhook(request.body, request.headers.get("X-Paystack-Signature"))
    return HttpResponse(status=status)
