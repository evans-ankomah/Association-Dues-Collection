"""Dues types, assessments and waivers."""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record, snapshot
from apps.memberships.models import DepartmentMembership

from ..models import DuesAssessment, DuesType, WaiverRequest
from ..signals import waiver_decided
from .balances import assessment_balance
from .errors import FinanceError, require_perm


def eligible_memberships(dues_type, levels=None, programmes=None):
    """Active members of the dues type's department and session who aren't assessed yet."""
    qs = DepartmentMembership.objects.filter(
        department_id=dues_type.department_id,
        academic_session_id=dues_type.academic_session_id,
        membership_status=DepartmentMembership.Status.ACTIVE,
    )
    if levels:
        qs = qs.filter(level_code__in=levels)
    if programmes:
        qs = qs.filter(programme_name__in=programmes)
    already = DuesAssessment.objects.filter(dues_type=dues_type).exclude(
        assessment_state=DuesAssessment.State.CANCELLED
    )
    return qs.exclude(pk__in=already.values("department_membership_id"))


@transaction.atomic
def assess(dues_type, *, actor, levels=None, programmes=None, amount=None, due_date=None):
    """Create assessments for every eligible member. Returns the number created."""
    require_perm(actor, "dues.assessment.create", dues_type.department)
    dues_type = DuesType.objects.select_for_update().get(pk=dues_type.pk)
    if not dues_type.can_assess:
        raise FinanceError("This dues type is closed or cancelled, so no one can be assessed for it.")
    amount = dues_type.default_amount if amount is None else Decimal(amount)
    if amount <= 0:
        raise FinanceError("The amount must be greater than zero.")

    memberships = list(eligible_memberships(dues_type, levels, programmes).values_list("pk", flat=True))
    if not memberships:
        return 0
    now = timezone.now()
    DuesAssessment.objects.bulk_create(
        DuesAssessment(
            dues_type=dues_type,
            department_membership_id=membership_id,
            amount_assessed=amount,
            due_date=due_date or dues_type.due_date,
            assessed_by=actor,
            assessed_at=now,
        )
        for membership_id in memberships
    )
    if dues_type.status == DuesType.Status.DRAFT:
        dues_type.status = DuesType.Status.ACTIVE
        dues_type.save(update_fields=["status"])
    record(
        "dues.assessed",
        dues_type,
        actor=actor,
        department=dues_type.department,
        after={
            "count": len(memberships),
            "amount": str(amount),
            "levels": levels or [],
            "programmes": programmes or [],
        },
    )
    return len(memberships)


@transaction.atomic
def cancel_assessment(assessment, *, actor, reason):
    department = assessment.dues_type.department
    require_perm(actor, "dues.assessment.create", department)
    assessment = DuesAssessment.objects.select_for_update().get(pk=assessment.pk)
    if assessment.assessment_state == DuesAssessment.State.CANCELLED:
        raise FinanceError("This assessment is already cancelled.")
    if assessment.allocations.exists():
        raise FinanceError("Payments have been allocated to this assessment. Refund or reverse them first.")
    if not (reason or "").strip():
        raise FinanceError("Give a reason for cancelling.")
    before = snapshot(assessment)
    assessment.assessment_state = DuesAssessment.State.CANCELLED
    assessment.save(update_fields=["assessment_state"])
    record(
        "dues.assessment_cancelled",
        assessment,
        actor=actor,
        department=department,
        before=before,
        after={**snapshot(assessment), "reason": reason.strip()},
    )
    return assessment


def _waivable(assessment):
    return max(assessment_balance(assessment), Decimal("0"))


@transaction.atomic
def request_waiver(assessment, *, actor, amount, reason):
    """Ask for a waiver. Members may ask for their own; finance officers for anyone."""
    department = assessment.dues_type.department
    is_own = assessment.department_membership.user_id == actor.pk
    if not is_own:
        require_perm(actor, "dues.assessment.create", department)
    assessment = DuesAssessment.objects.select_for_update().get(pk=assessment.pk)
    if assessment.assessment_state != DuesAssessment.State.ACTIVE:
        raise FinanceError("Only active assessments can be waived.")
    amount = Decimal(amount)
    if amount <= 0:
        raise FinanceError("The waiver amount must be greater than zero.")
    if amount > _waivable(assessment):
        raise FinanceError("A waiver can't be more than the outstanding balance.")
    if not (reason or "").strip():
        raise FinanceError("Explain why the waiver is needed.")
    if assessment.waiver_requests.filter(status=WaiverRequest.Status.PENDING).exists():
        raise FinanceError("There's already a waiver request waiting for a decision.")
    request = WaiverRequest.objects.create(
        dues_assessment=assessment, amount=amount, reason=reason.strip(), requested_by=actor
    )
    record("dues.waiver_requested", request, actor=actor, department=department, after=snapshot(request))
    return request


@transaction.atomic
def decide_waiver(waiver, *, actor, approve, note=""):
    assessment = waiver.dues_assessment
    department = assessment.dues_type.department
    require_perm(actor, "dues.waiver.approve", department)
    waiver = WaiverRequest.objects.select_for_update().get(pk=waiver.pk)
    if waiver.status != WaiverRequest.Status.PENDING:
        raise FinanceError("This request has already been decided.")
    if waiver.requested_by_id == actor.pk:
        raise FinanceError("You can't decide a waiver you requested.")
    if assessment.department_membership.user_id == actor.pk:
        raise FinanceError("You can't decide a waiver on your own dues.")

    assessment = DuesAssessment.objects.select_for_update().get(pk=assessment.pk)
    now = timezone.now()
    if approve:
        if assessment.assessment_state != DuesAssessment.State.ACTIVE:
            raise FinanceError("The assessment is no longer active.")
        if waiver.amount > _waivable(assessment):
            raise FinanceError("The balance is now lower than the requested waiver. Reject and ask again.")
        before = snapshot(assessment)
        assessment.amount_waived += waiver.amount
        reasons = [r for r in (assessment.waiver_reason, waiver.reason) if r]
        assessment.waiver_reason = "\n".join(reasons)
        assessment.waived_by = actor
        assessment.waived_at = now
        if assessment.amount_waived == assessment.amount_assessed:
            assessment.assessment_state = DuesAssessment.State.WAIVED
        assessment.save()
        record(
            "dues.waiver_approved",
            assessment,
            actor=actor,
            department=department,
            before=before,
            after=snapshot(assessment),
        )
    else:
        record("dues.waiver_rejected", waiver, actor=actor, department=department, after={"note": note})

    waiver.status = WaiverRequest.Status.APPROVED if approve else WaiverRequest.Status.REJECTED
    waiver.decided_by = actor
    waiver.decided_at = now
    waiver.decision_note = note or None
    waiver.save()
    transaction.on_commit(lambda: waiver_decided.send(sender=WaiverRequest, waiver=waiver))
    return waiver


@transaction.atomic
def set_dues_type_status(dues_type, *, actor, status):
    require_perm(actor, "dues.assessment.create", dues_type.department)
    allowed = {
        DuesType.Status.DRAFT: {DuesType.Status.ACTIVE, DuesType.Status.CANCELLED},
        DuesType.Status.ACTIVE: {DuesType.Status.CLOSED},
        DuesType.Status.CLOSED: {DuesType.Status.ACTIVE},
        DuesType.Status.CANCELLED: set(),
    }
    dues_type = DuesType.objects.select_for_update().get(pk=dues_type.pk)
    if status not in allowed[dues_type.status]:
        raise FinanceError(f"A {dues_type.status} dues type can't be changed to {status}.")
    if status == DuesType.Status.CANCELLED and dues_type.assessments.exists():
        raise FinanceError("Members have been assessed for this dues type. Close it instead.")
    before = {"status": dues_type.status}
    dues_type.status = status
    dues_type.save(update_fields=["status"])
    record(
        "dues.type_status_changed",
        dues_type,
        actor=actor,
        department=dues_type.department,
        before=before,
        after={"status": status},
    )
    return dues_type
