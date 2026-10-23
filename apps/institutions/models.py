from django.db import models
from django.db.models import F, Q

from apps.common.models import CurrencyField, TimeStampedModel


class Institution(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active"
        SUSPENDED = "suspended"
        ARCHIVED = "archived"

    name = models.CharField(max_length=200)
    country_code = models.CharField(max_length=2)
    default_currency = CurrencyField()
    timezone = models.CharField(max_length=64, default="Africa/Accra")
    status = models.CharField(max_length=20, choices=Status, default=Status.ACTIVE)

    class Meta:
        db_table = "institutions"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Faculty(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active"
        INACTIVE = "inactive"

    institution = models.ForeignKey(Institution, on_delete=models.PROTECT, related_name="faculties")
    code = models.CharField(max_length=40, null=True, blank=True)
    name = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=Status, default=Status.ACTIVE)

    class Meta:
        db_table = "faculties"
        ordering = ["name"]
        verbose_name_plural = "faculties"
        constraints = [
            models.UniqueConstraint(
                fields=["institution", "code"],
                condition=Q(code__isnull=False),
                name="uq_faculty_code_per_institution",
            )
        ]

    def __str__(self):
        return self.name


class Department(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active"
        SUSPENDED = "suspended"
        ARCHIVED = "archived"

    institution = models.ForeignKey(Institution, on_delete=models.PROTECT, related_name="departments")
    faculty = models.ForeignKey(
        Faculty, on_delete=models.PROTECT, null=True, blank=True, related_name="departments"
    )
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=200)
    short_name = models.CharField(max_length=80, null=True, blank=True)
    official_email = models.EmailField(max_length=254, null=True, blank=True)
    default_currency = CurrencyField()
    timezone = models.CharField(max_length=64, default="Africa/Accra")
    status = models.CharField(max_length=20, choices=Status, default=Status.ACTIVE)

    class Meta:
        db_table = "departments"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["institution", "code"], name="uq_department_code_per_institution")
        ]

    def __str__(self):
        return self.short_name or self.name


class AcademicSession(TimeStampedModel):
    class Status(models.TextChoices):
        PLANNED = "planned"
        ACTIVE = "active"
        CLOSED = "closed"
        ARCHIVED = "archived"

    institution = models.ForeignKey(Institution, on_delete=models.PROTECT, related_name="sessions")
    name = models.CharField(max_length=100)
    starts_on = models.DateField()
    ends_on = models.DateField()
    is_current = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=Status, default=Status.PLANNED)

    class Meta:
        db_table = "academic_sessions"
        ordering = ["-starts_on"]
        constraints = [
            models.UniqueConstraint(fields=["institution", "name"], name="uq_session_name_per_institution"),
            models.UniqueConstraint(
                fields=["institution"],
                condition=Q(is_current=True),
                name="uq_one_current_session_per_institution",
            ),
            models.CheckConstraint(condition=Q(ends_on__gte=F("starts_on")), name="ck_session_dates_ordered"),
        ]

    def __str__(self):
        return self.name

    @property
    def is_open(self):
        return self.status in (self.Status.PLANNED, self.Status.ACTIVE)
