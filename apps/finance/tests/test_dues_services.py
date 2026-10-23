from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from apps.audit.models import AuditEvent
from apps.finance.models import DuesAssessment, DuesType, WaiverRequest
from apps.finance.services import dues as svc
from apps.finance.services.balances import assessment_balance
from apps.finance.services.errors import FinanceError
from apps.memberships.models import DepartmentMembership

from .factories import pay

pytestmark = pytest.mark.django_db


def test_assess_targets_active_members_by_level_and_skips_duplicates(dues_type, finsec, make_membership):
    level_100 = make_membership(level_code="Level 100")
    make_membership(level_code="Level 200")
    make_membership(level_code="Level 100", membership_status=DepartmentMembership.Status.GRADUATED)

    assert svc.assess(dues_type, actor=finsec, levels=["Level 100"]) == 1
    assert DuesAssessment.objects.get().department_membership == level_100
    assert svc.assess(dues_type, actor=finsec, levels=["Level 100"]) == 0
    assert AuditEvent.objects.filter(action_key="dues.assessed").count() == 1


def test_assess_activates_draft_type_and_uses_custom_amount(dues_type, finsec, make_membership):
    dues_type.status = DuesType.Status.DRAFT
    dues_type.save()
    make_membership()
    svc.assess(dues_type, actor=finsec, amount=Decimal("75.50"))
    dues_type.refresh_from_db()
    assert dues_type.status == DuesType.Status.ACTIVE
    assert DuesAssessment.objects.get().amount_assessed == Decimal("75.50")


def test_cannot_assess_closed_type(dues_type, finsec, make_membership):
    make_membership()
    dues_type.status = DuesType.Status.CLOSED
    dues_type.save()
    with pytest.raises(FinanceError):
        svc.assess(dues_type, actor=finsec)


def test_assess_requires_permission(dues_type, member):
    with pytest.raises(PermissionDenied):
        svc.assess(dues_type, actor=member)


def test_waiver_flow_requires_a_different_approver(assessment, finsec, hod):
    request = svc.request_waiver(assessment, actor=finsec, amount="50.00", reason="Hardship")
    with pytest.raises(PermissionDenied):
        svc.decide_waiver(request, actor=finsec, approve=True)
    svc.decide_waiver(request, actor=hod, approve=True)
    assessment.refresh_from_db()
    assert assessment.amount_waived == Decimal("50.00")
    assert assessment.waived_by == hod
    assert assessment_balance(assessment) == Decimal("100.00")
    assert WaiverRequest.objects.get().status == WaiverRequest.Status.APPROVED


def test_approver_cannot_decide_own_request(assessment, make_user, department):
    from apps.common.tests.factories import grant

    both = make_user("financial_secretary")
    grant(both, "hod_faculty_adviser", department)
    request = svc.request_waiver(assessment, actor=both, amount="10.00", reason="x")
    with pytest.raises(FinanceError, match="you requested"):
        svc.decide_waiver(request, actor=both, approve=True)


def test_member_can_request_own_waiver_but_not_others(assessment, member, make_user):
    svc.request_waiver(assessment, actor=member, amount="20.00", reason="Medical leave")
    stranger = make_user("student_member")
    with pytest.raises(PermissionDenied):
        svc.request_waiver(assessment, actor=stranger, amount="20.00", reason="x")


def test_full_waiver_marks_assessment_waived(assessment, finsec, hod):
    request = svc.request_waiver(assessment, actor=finsec, amount="150.00", reason="Medical leave")
    svc.decide_waiver(request, actor=hod, approve=True)
    assessment.refresh_from_db()
    assert assessment.assessment_state == DuesAssessment.State.WAIVED


def test_waiver_cannot_exceed_balance(assessment, finsec):
    pay(assessment, "100.00")
    with pytest.raises(FinanceError, match="more than the outstanding"):
        svc.request_waiver(assessment, actor=finsec, amount="60.00", reason="x")


def test_only_one_pending_waiver(assessment, finsec):
    svc.request_waiver(assessment, actor=finsec, amount="10.00", reason="x")
    with pytest.raises(FinanceError, match="already"):
        svc.request_waiver(assessment, actor=finsec, amount="10.00", reason="y")


def test_rejected_waiver_leaves_assessment_unchanged(assessment, finsec, hod):
    request = svc.request_waiver(assessment, actor=finsec, amount="10.00", reason="x")
    svc.decide_waiver(request, actor=hod, approve=False, note="Not eligible")
    assessment.refresh_from_db()
    assert assessment.amount_waived == 0
    with pytest.raises(FinanceError, match="already been decided"):
        svc.decide_waiver(request, actor=hod, approve=True)


def test_cancel_blocked_once_paid(assessment, finsec):
    pay(assessment, "10.00")
    with pytest.raises(FinanceError, match="Refund or reverse"):
        svc.cancel_assessment(assessment, actor=finsec, reason="Mistake")


def test_cancel_unpaid_assessment(assessment, finsec):
    svc.cancel_assessment(assessment, actor=finsec, reason="Assessed by mistake")
    assessment.refresh_from_db()
    assert assessment.assessment_state == DuesAssessment.State.CANCELLED


def test_status_transitions(dues_type, finsec):
    svc.set_dues_type_status(dues_type, actor=finsec, status=DuesType.Status.CLOSED)
    with pytest.raises(FinanceError):
        svc.set_dues_type_status(dues_type, actor=finsec, status=DuesType.Status.CANCELLED)
