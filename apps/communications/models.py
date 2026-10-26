from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.common.models import TimeStampedModel
from apps.institutions.models import Department


class Announcement(TimeStampedModel):
    class Audience(models.TextChoices):
        ALL_MEMBERS = "all_members", "All members"
        SELECTED_LEVELS = "selected_levels", "Selected levels"
        SELECTED_PROGRAMMES = "selected_programmes", "Selected programmes"
        COMMITTEE = "committee"
        EXECUTIVES = "executives"

    class Priority(models.TextChoices):
        NORMAL = "normal"
        IMPORTANT = "important"
        URGENT = "urgent"

    class Status(models.TextChoices):
        DRAFT = "draft"
        SCHEDULED = "scheduled"
        PUBLISHED = "published"
        ARCHIVED = "archived"
        CANCELLED = "cancelled"

    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="announcements")
    title = models.CharField(max_length=180)
    body = models.TextField()
    audience_type = models.CharField(max_length=30, choices=Audience, default=Audience.ALL_MEMBERS)
    # {"levels": [...]} or {"programmes": [...]}
    audience_filter = models.JSONField(null=True, blank=True)
    priority = models.CharField(max_length=20, choices=Priority, default=Priority.NORMAL)
    announcement_status = models.CharField(max_length=20, choices=Status, default=Status.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    published_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "announcements"
        ordering = ["-published_at", "-created_at"]
        indexes = [models.Index(fields=["department", "announcement_status", "published_at"])]

    def __str__(self):
        return self.title

    @property
    def needs_acknowledgement(self):
        return self.priority in (self.Priority.IMPORTANT, self.Priority.URGENT)

    @property
    def levels(self):
        return (self.audience_filter or {}).get("levels", [])

    @property
    def programmes(self):
        return (self.audience_filter or {}).get("programmes", [])


def live_announcements(at=None):
    """Published (or scheduled and due) and not expired."""
    at = at or timezone.now()
    return Announcement.objects.filter(
        Q(announcement_status=Announcement.Status.PUBLISHED)
        | Q(announcement_status=Announcement.Status.SCHEDULED, published_at__lte=at),
        published_at__lte=at,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=at))


class AnnouncementAcknowledgement(TimeStampedModel):
    """Not in the workbook: who has read/acknowledged an important notice."""

    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name="acknowledgements")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    acknowledged_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "announcement_acknowledgements"
        constraints = [models.UniqueConstraint(fields=["announcement", "user"], name="uq_announcement_ack")]


class Notification(TimeStampedModel):
    class Channel(models.TextChoices):
        IN_APP = "in_app", "In app"
        EMAIL = "email"
        SMS = "sms", "SMS"
        PUSH = "push"

    class Status(models.TextChoices):
        QUEUED = "queued"
        SENT = "sent"
        DELIVERED = "delivered"
        FAILED = "failed"
        READ = "read"
        CANCELLED = "cancelled"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    channel = models.CharField(max_length=20, choices=Channel)
    notification_type = models.CharField(max_length=80)
    title = models.CharField(max_length=180)
    body = models.TextField()
    delivery_status = models.CharField(max_length=24, choices=Status, default=Status.QUEUED)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    delivery_error_code = models.CharField(max_length=100, null=True, blank=True)
    # Not in the workbook: where the in-app notification links to, and a key that stops
    # the same reminder being sent twice.
    link = models.CharField(max_length=300, null=True, blank=True)
    dedupe_key = models.CharField(max_length=200, null=True, blank=True)

    class Meta:
        db_table = "notifications"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "channel", "read_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "channel", "dedupe_key"],
                condition=Q(dedupe_key__isnull=False),
                name="uq_notification_dedupe",
            )
        ]

    def __str__(self):
        return f"{self.channel}: {self.title}"
