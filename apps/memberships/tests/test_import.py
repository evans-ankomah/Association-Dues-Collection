import io

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from apps.access.services import has_perm
from apps.accounts.models import User, UserProfile
from apps.audit.models import AuditEvent
from apps.common.tests.factories import UserFactory
from apps.memberships import importing
from apps.memberships.models import DepartmentMembership

pytestmark = pytest.mark.django_db

CSV = (
    "Email,First name,Surname,Index number,Phone,Programme,Level\n"
    "kofi.new@st.example.test,Kofi,Mensah,CE-2026-0001,024 123 4567,BSc CSE,Level 100\n"
    "BAD-EMAIL,Ama,Owusu,,,BSc CSE,Level 100\n"
    "kofi.new@st.example.test,Kofi,Again,,,BSc CSE,Level 100\n"
)


@pytest.fixture
def secretary(make_user):
    return make_user("department_secretary")


def upload(text, name="roster.csv"):
    return SimpleUploadedFile(name, text.encode(), content_type="text/csv")


def test_parse_flags_problems(department, session):
    rows = importing.parse_roster(io.BytesIO(CSV.encode()), department=department, session=session)
    assert [r.action for r in rows] == ["new_user", "error", "error"]
    assert rows[0].phone_number == "233241234567"
    assert "email isn't valid" in rows[1].errors
    assert "email appears twice in the file" in rows[2].errors


def test_student_number_clash_detected(department, session):
    other = UserFactory(email="someone@example.test", with_profile__institution=department.institution)
    UserProfile.objects.filter(user=other).update(student_number="CE-1")
    text = "email,given_name,family_name,student_number\nnew@example.test,A,B,CE-1\n"
    rows = importing.parse_roster(io.BytesIO(text.encode()), department=department, session=session)
    assert rows[0].errors == ["student number belongs to a different email"]


def test_preview_then_confirm_creates_members_with_role(secretary, login, department, session):
    client = login(secretary)
    preview = client.post("/members/import/", {"roster": upload(CSV)})
    assert preview.context["preview"]["valid"] == 1
    assert not User.objects.filter(email="kofi.new@st.example.test").exists()  # nothing saved yet

    client.post("/members/import/", {"confirm": "1", "send_welcome": "1"})
    user = User.objects.get(email="kofi.new@st.example.test")
    assert not user.has_usable_password()
    membership = DepartmentMembership.objects.get(user=user, academic_session=session)
    assert membership.level_code == "Level 100" and membership.verified_by == secretary
    assert has_perm(user, "dues.own.view", department)
    assert len(mail.outbox) == 1 and mail.outbox[0].to == [user.email]
    assert AuditEvent.objects.filter(action_key="members.roster_imported").exists()


def test_existing_member_is_updated_not_duplicated(secretary, login, member, session):
    text = f"email,given_name,family_name,level_code\n{member.email},Ama,Mensah,Level 300\n"
    client = login(secretary)
    preview = client.post("/members/import/", {"roster": upload(text)})
    assert preview.context["preview"]["counts"]["update"] == 1
    client.post("/members/import/", {"confirm": "1"})
    assert (
        DepartmentMembership.objects.filter(user=member, academic_session=session).get().level_code
        == "Level 300"
    )


def test_excel_upload(secretary, login, session):
    workbook = Workbook()
    workbook.active.append(["email", "given_name", "family_name", "level_code"])
    workbook.active.append(["xl@example.test", "Esi", "Boateng", "Level 200"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    file = SimpleUploadedFile("roster.xlsx", buffer.getvalue())
    preview = login(secretary).post("/members/import/", {"roster": file})
    assert preview.context["preview"]["counts"]["new_user"] == 1


def test_only_roster_editors(make_user, login):
    assert login(make_user("treasurer")).get("/members/import/").status_code == 403
