from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel
from apps.institutions.models import Department

CATEGORIES = [
    ("policy", "Policy"),
    ("template", "Template"),
    ("minutes", "Meeting minutes"),
    ("report", "Report"),
    ("financial", "Financial evidence"),
    ("handover", "Handover notes"),
    ("other", "Other"),
]


class DocumentQuerySet(models.QuerySet):
    def current(self):
        """The newest version of each document (one nobody has superseded)."""
        superseded = Document.objects.filter(previous_version__isnull=False).values("previous_version_id")
        return self.exclude(pk__in=superseded)


class Document(TimeStampedModel):
    class Visibility(models.TextChoices):
        OWNER_ONLY = "owner_only", "Only me"
        DEPARTMENT = "department", "Department members"
        COMMITTEE = "committee", "Committee members"
        COLLABORATION = "collaboration", "Collaboration partners"
        PUBLIC = "public", "Anyone signed in"

    class ReviewStatus(models.TextChoices):
        DRAFT = "draft"
        PENDING_REVIEW = "pending_review", "Pending review"
        APPROVED = "approved"
        REJECTED = "rejected"
        ARCHIVED = "archived"

    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="documents")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    title = models.CharField(max_length=180)
    category = models.CharField(max_length=60, choices=CATEGORIES, default="other")
    original_filename = models.CharField(max_length=255)
    # A key into the private document store, never a public URL.
    storage_key = models.TextField()
    mime_type = models.CharField(max_length=120)
    file_size_bytes = models.BigIntegerField()
    checksum_sha256 = models.CharField(max_length=64)
    visibility = models.CharField(max_length=24, choices=Visibility, default=Visibility.DEPARTMENT)
    version_number = models.PositiveIntegerField(default=1)
    previous_version = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="next_versions",
        db_column="previous_version_document_id",
    )
    review_status = models.CharField(max_length=24, choices=ReviewStatus, default=ReviewStatus.DRAFT)
    uploaded_at = models.DateTimeField(default=timezone.now)

    objects = DocumentQuerySet.as_manager()

    class Meta:
        db_table = "documents"
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(fields=["department", "category"]),
            models.Index(fields=["department", "visibility"]),
        ]

    def __str__(self):
        return self.title

    @property
    def is_superseded(self):
        return self.next_versions.exists()

    @property
    def size_display(self):
        size = float(self.file_size_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} GB"
