from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.common.models import TimeStampedModel
from apps.institutions.models import AcademicSession, Department, Institution


class Role(TimeStampedModel):
    class Scope(models.TextChoices):
        PLATFORM = "platform"
        INSTITUTION = "institution"
        DEPARTMENT = "department"

    role_code = models.CharField(max_length=60, unique=True)
    name = models.CharField(max_length=100)
    scope_type = models.CharField(max_length=30, choices=Scope)
    description = models.TextField(null=True, blank=True)
    is_system_role = models.BooleanField(default=False)
    permissions = models.ManyToManyField("Permission", through="RolePermission", related_name="roles")

    class Meta:
        db_table = "roles"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Permission(TimeStampedModel):
    permission_code = models.CharField(max_length=100, unique=True)
    module_key = models.CharField(max_length=60)
    action_key = models.CharField(max_length=60)
    description = models.TextField()

    class Meta:
        db_table = "permissions"
        ordering = ["permission_code"]

    def __str__(self):
        return self.permission_code


class RolePermission(TimeStampedModel):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="grants")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name="grants")
    # The workbook makes this NOT NULL; system grants created by migration have no human author.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "role_permissions"
        constraints = [models.UniqueConstraint(fields=["role", "permission"], name="uq_role_permission")]

    def __str__(self):
        return f"{self.role.role_code} → {self.permission.permission_code}"


class RoleAssignmentQuerySet(models.QuerySet):
    def current(self, at=None):
        at = at or timezone.now()
        return self.filter(
            assignment_status=RoleAssignment.Status.ACTIVE,
            starts_at__lte=at,
        ).filter(Q(ends_at__isnull=True) | Q(ends_at__gt=at))


class RoleAssignment(TimeStampedModel):
    """A time-bounded grant of a role to a user within an explicit scope."""

    class Status(models.TextChoices):
        ACTIVE = "active"
        ENDED = "ended"
        REVOKED = "revoked"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="role_assignments"
    )
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="assignments")
    institution = models.ForeignKey(Institution, on_delete=models.PROTECT, null=True, blank=True)
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, null=True, blank=True, related_name="role_assignments"
    )
    academic_session = models.ForeignKey(AcademicSession, on_delete=models.PROTECT, null=True, blank=True)
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(null=True, blank=True)
    assignment_status = models.CharField(max_length=20, choices=Status, default=Status.ACTIVE)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    objects = RoleAssignmentQuerySet.as_manager()

    class Meta:
        db_table = "role_assignments"
        ordering = ["-starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__isnull=True) | Q(ends_at__gt=F("starts_at")),
                name="ck_role_assignment_dates_ordered",
            ),
            models.UniqueConstraint(
                fields=["user", "role", "institution", "department", "academic_session"],
                condition=Q(assignment_status="active"),
                nulls_distinct=False,
                name="uq_one_active_grant_per_scope",
            ),
        ]
        indexes = [models.Index(fields=["user", "assignment_status"])]

    def __str__(self):
        scope = self.department or self.institution or "platform"
        return f"{self.user} · {self.role.role_code} · {scope}"

    def clean(self):
        scope = self.role.scope_type if self.role_id else None
        if scope == Role.Scope.DEPARTMENT and not self.department_id:
            raise ValidationError({"department": "A department role needs a department."})
        if scope == Role.Scope.INSTITUTION and (not self.institution_id or self.department_id):
            raise ValidationError("An institution role needs an institution and no department.")
        if scope == Role.Scope.PLATFORM and (self.institution_id or self.department_id):
            raise ValidationError("A platform role must not be limited to an institution or department.")
