from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel
from apps.institutions.models import Department
from apps.memberships.models import DepartmentMembership

# Statuses that mean the request is finished and should drop out of the open queue.
CLOSED_STATES = ("resolved", "rejected", "closed")

# Request types whose subject matter is sensitive. These are forced to `restricted`
# visibility on submission, per the product plan: sensitive categories must not land
# in a general queue without safeguards.
SENSITIVE_TYPES = {"welfare", "result_query", "complaint", "harassment"}

REQUEST_TYPES = [
    ("introductory_letter", "Introductory or official letter"),
    ("lab_access", "Laboratory or facility access"),
    ("equipment_fault", "Report broken equipment"),
    ("venue_booking", "Venue or resource request"),
    ("dues_query", "Dues or payment query"),
    ("result_query", "Result or grade query"),
    ("admin_question", "Administrative question"),
    ("welfare", "Private welfare concern"),
    ("other", "Something else"),
]


class ServiceRequestQuerySet(models.QuerySet):
    def open(self):
        return self.exclude(request_status__in=CLOSED_STATES)

    def department_visible(self):
        """Requests an officer may see in the general queue (excludes restricted ones)."""
        return self.filter(visibility_level=ServiceRequest.Visibility.DEPARTMENT)


class ServiceRequest(TimeStampedModel):
    class Priority(models.TextChoices):
        LOW = "low"
        NORMAL = "normal"
        HIGH = "high"
        URGENT = "urgent"

    class Status(models.TextChoices):
        SUBMITTED = "submitted"
        TRIAGED = "triaged"
        IN_PROGRESS = "in_progress", "In progress"
        WAITING = "waiting", "Waiting on requester"
        RESOLVED = "resolved"
        REJECTED = "rejected"
        CLOSED = "closed"

    class Visibility(models.TextChoices):
        DEPARTMENT = "department", "Department officers"
        RESTRICTED = "restricted", "Requester and assignee only"

    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="service_requests")
    requester_membership = models.ForeignKey(
        DepartmentMembership, on_delete=models.PROTECT, related_name="service_requests"
    )
    request_type = models.CharField(max_length=60)
    title = models.CharField(max_length=180)
    description = models.TextField()
    priority = models.CharField(max_length=20, choices=Priority, default=Priority.NORMAL)
    request_status = models.CharField(max_length=24, choices=Status, default=Status.SUBMITTED)
    assigned_to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    submitted_at = models.DateTimeField(default=timezone.now)
    due_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_summary = models.TextField(null=True, blank=True)
    visibility_level = models.CharField(max_length=24, choices=Visibility, default=Visibility.DEPARTMENT)

    objects = ServiceRequestQuerySet.as_manager()

    class Meta:
        db_table = "service_requests"
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["department", "request_status", "submitted_at"]),
            models.Index(fields=["department", "visibility_level"]),
        ]

    def __str__(self):
        return self.title

    @property
    def is_restricted(self):
        return self.visibility_level == self.Visibility.RESTRICTED

    @property
    def is_closed(self):
        return self.request_status in CLOSED_STATES

    @property
    def is_overdue(self):
        return bool(self.due_at and not self.is_closed and self.due_at < timezone.now())

    @property
    def requester_user_id(self):
        return self.requester_membership.user_id


class ServiceRequestComment(TimeStampedModel):
    class Visibility(models.TextChoices):
        REQUESTER_VISIBLE = "requester_visible", "Visible to the requester"
        STAFF_ONLY = "staff_only", "Staff only"

    service_request = models.ForeignKey(ServiceRequest, on_delete=models.CASCADE, related_name="comments")
    author_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    body = models.TextField()
    visibility = models.CharField(max_length=24, choices=Visibility, default=Visibility.REQUESTER_VISIBLE)

    class Meta:
        db_table = "service_request_comments"
        ordering = ["created_at"]
        indexes = [models.Index(fields=["service_request", "visibility"])]

    def __str__(self):
        return f"{self.author_user} on {self.service_request}"
