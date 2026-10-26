import datetime

import pytest
from django.core import mail
from django.utils import timezone

from apps.common.tests.factories import MembershipFactory
from apps.communications.delivery import notify
from apps.communications.models import Announcement, AnnouncementAcknowledgement, Notification
from apps.communications.services import audience_users, publish, visible_announcements
from apps.finance.services import dues as dues_service
from apps.finance.services import payments as pay_service
from apps.finance.tests.factories import AssessmentFactory, DuesTypeFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def secretary(make_user):
    return make_user("department_secretary")


@pytest.fixture
def level_members(department, session, make_user):
    def make(level):
        user = make_user("student_member")
        MembershipFactory(user=user, department=department, academic_session=session, level_code=level)
        return user

    return {"100": make("Level 100"), "200": make("Level 200")}


def announcement(department, author, **kwargs):
    return Announcement.objects.create(
        department=department, title="Notice", body="Body", created_by=author, **kwargs
    )


def test_level_targeting(department, secretary, level_members):
    a = announcement(
        department, secretary, audience_type="selected_levels", audience_filter={"levels": ["Level 100"]}
    )
    publish(a, actor=secretary)
    assert set(audience_users(a)) == {level_members["100"]}
    assert a in visible_announcements(level_members["100"], department)
    assert a not in visible_announcements(level_members["200"], department)
    assert a in visible_announcements(secretary, department)  # publishers see everything


def test_scheduled_and_expired_notices_are_hidden(department, secretary, level_members):
    future = announcement(department, secretary)
    publish(future, actor=secretary, at=timezone.now() + datetime.timedelta(days=1))
    expired = announcement(department, secretary, expires_at=timezone.now() - datetime.timedelta(minutes=1))
    expired.announcement_status = "published"
    expired.published_at = timezone.now() - datetime.timedelta(days=2)
    expired.save()
    assert list(visible_announcements(level_members["100"], department)) == []


def test_executive_notices_hidden_from_ordinary_members(department, secretary, level_members, make_user):
    treasurer = make_user("treasurer")
    a = announcement(department, secretary, audience_type="executives")
    publish(a, actor=secretary)
    assert a in visible_announcements(treasurer, department)
    assert a not in visible_announcements(level_members["100"], department)


def test_urgent_notice_notifies_audience_once(
    department, secretary, level_members, django_capture_on_commit_callbacks
):
    a = announcement(department, secretary, priority="urgent")
    with django_capture_on_commit_callbacks(execute=True):
        publish(a, actor=secretary)
    in_app = Notification.objects.filter(channel="in_app", notification_type="announcement")
    assert in_app.count() == 2
    from apps.communications.services import notify_audience

    notify_audience(a)  # a retry must not double-send
    assert in_app.count() == 2
    assert not Notification.objects.filter(channel="sms").exists()  # SMS disabled in tests


def test_member_cannot_publish(level_members, login):
    client = login(level_members["100"])
    assert client.get("/communications/announcements/new/").status_code == 403


def test_publish_and_acknowledge_through_views(secretary, level_members, login):
    client = login(secretary)
    client.post(
        "/communications/announcements/new/",
        {
            "title": "Dues deadline",
            "body": "Pay by Friday",
            "priority": "important",
            "audience_type": "all_members",
            "publish": "1",
        },
    )
    a = Announcement.objects.get()
    assert a.announcement_status == "published"

    member = login(level_members["200"])
    assert member.get(f"/communications/announcements/{a.pk}/").status_code == 200
    member.post(f"/communications/announcements/{a.pk}/acknowledge/")
    assert AnnouncementAcknowledgement.objects.filter(announcement=a, user=level_members["200"]).exists()
    stats = login(secretary).get(f"/communications/announcements/{a.pk}/").context["stats"]
    assert stats == {"audience": 2, "acknowledged": 1}


def test_email_respects_preferences(member):
    member.profile.email_notifications = False
    member.profile.save()
    created = notify(member, notification_type="t", title="Hi", body="Body")
    assert [n.channel for n in created] == ["in_app"]


def test_email_is_sent_and_marked(member, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        notify(member, notification_type="t", title="Hello", body="Body", channels=("email",))
    assert len(mail.outbox) == 1 and mail.outbox[0].to == [member.email]
    assert Notification.objects.get(channel="email").delivery_status == "sent"


def test_sms_only_with_backend_opt_in_and_phone(member, settings, django_capture_on_commit_callbacks):
    member.profile.sms_notifications = True
    member.profile.phone_number = "233241234567"
    member.profile.save()
    assert notify(member, notification_type="t", title="x", body="y", channels=("sms",)) == []
    settings.SMS_BACKEND = "console"
    with django_capture_on_commit_callbacks(execute=True):
        created = notify(member, notification_type="t", title="x", body="y", channels=("sms",))
    assert len(created) == 1
    created[0].refresh_from_db()
    assert created[0].delivery_status == "sent"


def test_queued_rows_from_elsewhere_are_never_sent(member, settings):
    settings.SMS_BACKEND = "console"
    Notification.objects.create(
        user=member,
        channel="sms",
        notification_type="dues_reminder",
        title="x",
        body="y",
        delivery_status="queued",
    )
    # Nothing sweeps the queue; only notify() schedules deliveries.
    assert Notification.objects.get().delivery_status == "queued"


def test_payment_confirmation_notifies_payer(
    member, membership, department, session, make_user, django_capture_on_commit_callbacks
):
    finsec = make_user("financial_secretary")
    dues_type = DuesTypeFactory(department=department, academic_session=session, created_by=finsec)
    AssessmentFactory(dues_type=dues_type, department_membership=membership)
    payment = pay_service.record_offline_payment(membership, actor=finsec, method="cash", amount="150")
    with django_capture_on_commit_callbacks(execute=True):
        receipt = pay_service.verify_payment(payment, actor=make_user("treasurer"))
    note = Notification.objects.get(user=member, channel="in_app")
    assert note.notification_type == "payment_confirmed"
    assert receipt.receipt_number in note.title
    assert dues_type.name in note.body


def test_waiver_decision_notifies_member(
    member, membership, department, session, make_user, django_capture_on_commit_callbacks
):
    finsec = make_user("financial_secretary")
    dues_type = DuesTypeFactory(department=department, academic_session=session, created_by=finsec)
    assessment = AssessmentFactory(dues_type=dues_type, department_membership=membership)
    waiver = dues_service.request_waiver(assessment, actor=finsec, amount="20", reason="Hardship")
    with django_capture_on_commit_callbacks(execute=True):
        dues_service.decide_waiver(waiver, actor=make_user("hod_faculty_adviser"), approve=True)
    assert Notification.objects.get(user=member, channel="in_app").title == "Waiver approved"


def test_bell_and_mark_read(member, login):
    notify(member, notification_type="t", title="Hello", body="Body", channels=("in_app",))
    client = login(member)
    assert client.get("/communications/notifications/bell/").context["unread_count"] == 1
    note = Notification.objects.get()
    response = client.get(f"/communications/notifications/{note.pk}/")
    assert response.status_code == 302
    note.refresh_from_db()
    assert note.read_at is not None
    assert client.get("/communications/notifications/bell/").context["unread_count"] == 0


def test_cannot_open_someone_elses_notification(member, make_user, login):
    other = make_user()
    notify(other, notification_type="t", title="Private", body="x", channels=("in_app",))
    note = Notification.objects.get()
    assert login(member).get(f"/communications/notifications/{note.pk}/").status_code == 404
