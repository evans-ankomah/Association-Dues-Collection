from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel
from apps.institutions.models import AcademicSession, Department
from apps.memberships.models import DepartmentMembership

OPEN_TASK_STATES = ("todo", "in_progress", "blocked")


class Committee(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active"
        INACTIVE = "inactive"
        ARCHIVED = "archived"

    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="committees")
    academic_session = models.ForeignKey(AcademicSession, on_delete=models.PROTECT, related_name="committees")
    name = models.CharField(max_length=140)
    description = models.TextField(null=True, blank=True)
    chair_membership = models.ForeignKey(
        DepartmentMembership,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="chaired_committees",
    )
    committee_status = models.CharField(max_length=20, choices=Status, default=Status.ACTIVE)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "committees"
        ordering = ["name"]
        indexes = [models.Index(fields=["department", "academic_session", "committee_status"])]

    def __str__(self):
        return self.name

    @property
    def active_members(self):
        return self.members.filter(membership_status=CommitteeMember.Status.ACTIVE)


class CommitteeMember(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active"
        ENDED = "ended"

    committee = models.ForeignKey(Committee, on_delete=models.CASCADE, related_name="members")
    department_membership = models.ForeignKey(
        DepartmentMembership, on_delete=models.PROTECT, related_name="committee_memberships"
    )
    role_title = models.CharField(max_length=80, null=True, blank=True)
    joined_at = models.DateTimeField(default=timezone.now)
    left_at = models.DateTimeField(null=True, blank=True)
    membership_status = models.CharField(max_length=20, choices=Status, default=Status.ACTIVE)

    class Meta:
        db_table = "committee_members"
        ordering = ["joined_at"]
        constraints = [
            models.UniqueConstraint(fields=["committee", "department_membership"], name="uq_committee_member")
        ]

    def __str__(self):
        return f"{self.department_membership} · {self.committee}"


class Meeting(TimeStampedModel):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled"
        HELD = "held"
        CANCELLED = "cancelled"

    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="meetings")
    committee = models.ForeignKey(
        Committee, on_delete=models.PROTECT, null=True, blank=True, related_name="meetings"
    )
    title = models.CharField(max_length=180)
    scheduled_at = models.DateTimeField()
    location_text = models.CharField(max_length=220, null=True, blank=True)
    meeting_status = models.CharField(max_length=20, choices=Status, default=Status.SCHEDULED)
    minutes_document = models.ForeignKey(
        "documents.Document",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="minutes_for",
        db_column="minutes_document_id",
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "meetings"
        ordering = ["-scheduled_at"]
        indexes = [models.Index(fields=["department", "meeting_status", "scheduled_at"])]

    def __str__(self):
        return self.title


class TaskQuerySet(models.QuerySet):
    def open(self):
        return self.filter(task_status__in=OPEN_TASK_STATES)

    def overdue(self, at=None):
        return self.open().filter(due_at__lt=at or timezone.now())


class Task(TimeStampedModel):
    class Status(models.TextChoices):
        TODO = "todo", "To do"
        IN_PROGRESS = "in_progress", "In progress"
        BLOCKED = "blocked"
        DONE = "done"
        CANCELLED = "cancelled"

    class Priority(models.TextChoices):
        LOW = "low"
        NORMAL = "normal"
        HIGH = "high"
        URGENT = "urgent"

    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="tasks")
    title = models.CharField(max_length=180)
    description = models.TextField(null=True, blank=True)
    task_status = models.CharField(max_length=24, choices=Status, default=Status.TODO)
    priority = models.CharField(max_length=20, choices=Priority, default=Priority.NORMAL)
    assigned_to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="tasks"
    )
    assigned_membership = models.ForeignKey(
        DepartmentMembership, on_delete=models.PROTECT, null=True, blank=True, related_name="tasks"
    )
    committee = models.ForeignKey(
        Committee, on_delete=models.PROTECT, null=True, blank=True, related_name="tasks"
    )
    event = models.ForeignKey(
        "events.Event", on_delete=models.PROTECT, null=True, blank=True, related_name="tasks"
    )
    meeting = models.ForeignKey(
        Meeting, on_delete=models.PROTECT, null=True, blank=True, related_name="tasks"
    )
    # Phase 4 (collaboration) adds the table this points at; kept nullable until then.
    collaboration_project_id = models.UUIDField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    due_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    objects = TaskQuerySet.as_manager()

    class Meta:
        db_table = "tasks"
        ordering = ["due_at", "-created_at"]
        indexes = [
            models.Index(fields=["department", "task_status", "due_at"]),
            models.Index(fields=["assigned_to_user", "task_status"]),
        ]

    def __str__(self):
        return self.title

    @property
    def is_open(self):
        return self.task_status in OPEN_TASK_STATES

    @property
    def is_overdue(self):
        return bool(self.due_at and self.is_open and self.due_at < timezone.now())
