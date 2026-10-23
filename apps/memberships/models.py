from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel
from apps.institutions.models import AcademicSession, Department


class MembershipQuerySet(models.QuerySet):
    def active(self):
        return self.filter(membership_status=DepartmentMembership.Status.ACTIVE)

    def for_department(self, department, session=None):
        qs = self.filter(department=department)
        if session is not None:
            qs = qs.filter(academic_session=session)
        return qs


class DepartmentMembership(TimeStampedModel):
    """A person's membership of one department for one academic session."""

    class Status(models.TextChoices):
        ACTIVE = "active"
        INACTIVE = "inactive"
        GRADUATED = "graduated"
        TRANSFERRED = "transferred"
        SUSPENDED = "suspended"

    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="memberships")
    academic_session = models.ForeignKey(
        AcademicSession, on_delete=models.PROTECT, related_name="memberships"
    )
    programme_name = models.CharField(max_length=160, null=True, blank=True)
    level_code = models.CharField(max_length=40, null=True, blank=True)
    membership_status = models.CharField(max_length=24, choices=Status, default=Status.ACTIVE)
    joined_on = models.DateField(null=True, blank=True)
    left_on = models.DateField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    objects = MembershipQuerySet.as_manager()

    class Meta:
        db_table = "department_memberships"
        ordering = ["level_code", "user__email"]
        constraints = [
            models.UniqueConstraint(
                fields=["department", "user", "academic_session"],
                name="uq_membership_per_department_session",
            )
        ]
        indexes = [models.Index(fields=["department", "academic_session", "membership_status"])]

    def __str__(self):
        return f"{self.user} · {self.department.code} · {self.academic_session}"
