import datetime
import json
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from apps.access import catalog
from apps.access.models import Role, RoleAssignment
from apps.access.services import accessible_departments, has_perm, permission_codes
from apps.common.tests.factories import DepartmentFactory, grant

pytestmark = pytest.mark.django_db


def test_member_gets_member_permissions_only(make_user, department):
    user = make_user("student_member")
    assert has_perm(user, "dues.own.view", department)
    assert has_perm(user, "finance.payment.initiate", department)
    assert not has_perm(user, "finance.payment.record", department)
    assert not has_perm(user, "finance.payment.verify", department)


def test_recording_and_verifying_are_separate_roles(make_user, department):
    secretary = make_user("financial_secretary")
    treasurer = make_user("treasurer")
    assert has_perm(secretary, "finance.payment.record", department)
    assert not has_perm(secretary, "finance.payment.verify", department)
    assert has_perm(treasurer, "finance.payment.verify", department)
    assert not has_perm(treasurer, "finance.payment.record", department)


def test_permissions_do_not_leak_to_other_departments(make_user, department):
    treasurer = make_user("treasurer")
    other = DepartmentFactory(institution=department.institution)
    assert has_perm(treasurer, "finance.payment.verify", department)
    assert not has_perm(treasurer, "finance.payment.verify", other)


@pytest.mark.parametrize(
    "overrides",
    [
        {"assignment_status": RoleAssignment.Status.ENDED},
        {"assignment_status": RoleAssignment.Status.REVOKED},
        {"ends_at": timezone.now() - datetime.timedelta(minutes=1)},
        {"starts_at": timezone.now() + datetime.timedelta(days=1)},
    ],
    ids=["ended", "revoked", "expired", "not-started"],
)
def test_non_current_assignments_grant_nothing(make_user, department, overrides):
    user = make_user()
    kwargs = {"starts_at": timezone.now() - datetime.timedelta(days=10), **overrides}
    grant(user, "treasurer", department, **kwargs)
    assert permission_codes(user, department) == frozenset()


def test_platform_admin_has_no_finance_authority(make_user, department):
    admin = make_user()
    grant(admin, "platform_admin")
    codes = permission_codes(admin, department)
    assert "platform.config.manage" in codes
    assert not any(code.startswith("finance.") for code in codes)
    assert department in accessible_departments(admin)


def test_hod_approves_but_cannot_record_or_verify(make_user, department):
    hod = make_user("hod_faculty_adviser")
    assert has_perm(hod, "dues.waiver.approve", department)
    assert has_perm(hod, "finance.adjustment.approve", department)
    assert not has_perm(hod, "finance.payment.record", department)
    assert not has_perm(hod, "finance.payment.verify", department)


def test_inactive_user_has_no_permissions(make_user, department):
    user = make_user("treasurer")
    user.is_active = False
    assert permission_codes(user, department) == frozenset()


def test_duplicate_active_grant_is_rejected(make_user, department):
    user = make_user("treasurer")
    with pytest.raises(IntegrityError):
        grant(user, "treasurer", department)


def test_department_role_requires_department(make_user):
    user = make_user()
    assignment = RoleAssignment(user=user, role=Role.objects.get(role_code="treasurer"))
    with pytest.raises(ValidationError):
        assignment.clean()


def test_catalog_installed_by_migration():
    assert Role.objects.count() == len(catalog.ROLES)
    treasurer = Role.objects.get(role_code="treasurer")
    assert treasurer.permissions.filter(permission_code="finance.payment.verify").exists()


SEED_DIR = Path(__file__).resolve().parents[3] / "seed" / "output" / "json"


@pytest.mark.skipif(not (SEED_DIR / "role_permissions.json").exists(), reason="seed data not generated")
def test_catalog_matches_seed_data():
    roles = {r["id"]: r["role_code"] for r in json.loads((SEED_DIR / "roles.json").read_text())}
    perms = {p["id"]: p["permission_code"] for p in json.loads((SEED_DIR / "permissions.json").read_text())}
    seed_grants = {
        (roles[g["role_id"]], perms[g["permission_id"]])
        for g in json.loads((SEED_DIR / "role_permissions.json").read_text())
    }
    code_grants = {(code, p) for code, *_rest, codes in catalog.ROLES for p in codes}
    assert code_grants == seed_grants
