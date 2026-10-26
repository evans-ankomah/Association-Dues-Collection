"""Announcement audiences, visibility and publishing."""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.access.models import RoleAssignment
from apps.access.services import has_perm
from apps.accounts.models import User
from apps.audit.services import record, snapshot
from apps.institutions.models import AcademicSession
from apps.memberships.models import DepartmentMembership

from .delivery import notify
from .models import Announcement, AnnouncementAcknowledgement, live_announcements

MEMBER_ROLE = "student_member"


def _current_session(department):
    return AcademicSession.objects.filter(institution_id=department.institution_id, is_current=True).first()


def executive_user_ids(department):
    """Users holding any current role in the department other than plain membership."""
    return (
        RoleAssignment.objects.current()
        .filter(department=department)
        .exclude(role__role_code=MEMBER_ROLE)
        .values_list("user_id", flat=True)
    )


def audience_users(announcement):
    """Everyone the announcement is addressed to."""
    department = announcement.department
    if announcement.audience_type in (Announcement.Audience.EXECUTIVES, Announcement.Audience.COMMITTEE):
        return User.objects.filter(pk__in=executive_user_ids(department), is_active=True)
    members = DepartmentMembership.objects.filter(
        department=department,
        academic_session=_current_session(department),
        membership_status=DepartmentMembership.Status.ACTIVE,
    )
    if announcement.audience_type == Announcement.Audience.SELECTED_LEVELS:
        members = members.filter(level_code__in=announcement.levels)
    elif announcement.audience_type == Announcement.Audience.SELECTED_PROGRAMMES:
        members = members.filter(programme_name__in=announcement.programmes)
    return User.objects.filter(pk__in=members.values("user_id"), is_active=True)


def visible_announcements(user, department):
    """Live announcements in `department` addressed to `user` (publishers see all live ones)."""
    qs = live_announcements().filter(department=department)
    if has_perm(user, "announcements.publish", department):
        return qs
    membership = DepartmentMembership.objects.filter(
        user=user, department=department, academic_session=_current_session(department)
    ).first()
    is_executive = user.pk in set(executive_user_ids(department))
    if membership is None and not is_executive:
        return qs.none()
    allowed = Q(audience_type=Announcement.Audience.ALL_MEMBERS)
    if membership is not None and membership.level_code:
        allowed |= Q(
            audience_type=Announcement.Audience.SELECTED_LEVELS,
            audience_filter__levels__contains=[membership.level_code],
        )
    if membership is not None and membership.programme_name:
        allowed |= Q(
            audience_type=Announcement.Audience.SELECTED_PROGRAMMES,
            audience_filter__programmes__contains=[membership.programme_name],
        )
    if is_executive:
        allowed |= Q(audience_type__in=[Announcement.Audience.EXECUTIVES, Announcement.Audience.COMMITTEE])
    return qs.filter(allowed)


def can_view(user, announcement):
    return visible_announcements(user, announcement.department).filter(pk=announcement.pk).exists()


def _require_publisher(actor, department):
    if not has_perm(actor, "announcements.publish", department):
        raise PermissionDenied


@transaction.atomic
def publish(announcement, *, actor, at=None):
    """Publish now, or schedule for `at`. Important and urgent notices also notify the audience."""
    _require_publisher(actor, announcement.department)
    now = timezone.now()
    before = snapshot(announcement)
    announcement.published_at = at or now
    announcement.announcement_status = (
        Announcement.Status.SCHEDULED if at and at > now else Announcement.Status.PUBLISHED
    )
    announcement.save()
    record(
        "announcement.published",
        announcement,
        actor=actor,
        department=announcement.department,
        before=before,
        after=snapshot(announcement),
    )
    if (
        announcement.announcement_status == Announcement.Status.PUBLISHED
        and announcement.needs_acknowledgement
    ):
        from .tasks import fan_out_announcement

        transaction.on_commit(lambda: fan_out_announcement.delay(str(announcement.pk)))
    return announcement


@transaction.atomic
def set_status(announcement, *, actor, status):
    _require_publisher(actor, announcement.department)
    before = {"status": announcement.announcement_status}
    announcement.announcement_status = status
    announcement.save(update_fields=["announcement_status"])
    record(
        f"announcement.{status}",
        announcement,
        actor=actor,
        department=announcement.department,
        before=before,
        after={"status": status},
    )
    return announcement


def notify_audience(announcement):
    link = reverse("communications:announcement", args=[announcement.pk])
    channels = (
        ("in_app", "email", "sms")
        if announcement.priority == Announcement.Priority.URGENT
        else (
            "in_app",
            "email",
        )
    )
    count = 0
    for user in audience_users(announcement).select_related("profile"):
        count += bool(
            notify(
                user,
                notification_type="announcement",
                title=announcement.title,
                body=announcement.body[:500],
                link=link,
                channels=channels,
                dedupe_key=f"announcement:{announcement.pk}",
            )
        )
    return count


def acknowledge(user, announcement):
    ack, _ = AnnouncementAcknowledgement.objects.get_or_create(announcement=announcement, user=user)
    return ack


def acknowledgement_stats(announcement):
    audience = audience_users(announcement)
    total = audience.count()
    acknowledged = AnnouncementAcknowledgement.objects.filter(
        announcement=announcement, user__in=audience
    ).count()
    return {"audience": total, "acknowledged": acknowledged}
