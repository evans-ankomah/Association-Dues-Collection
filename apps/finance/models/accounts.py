from django.db import models
from django.utils import timezone

from apps.common.models import CurrencyField, TimeStampedModel
from apps.institutions.models import Department


class FinancialAccount(TimeStampedModel):
    """A departmental cash box, bank, mobile-money or clearing account used for reconciliation."""

    class Type(models.TextChoices):
        CASH = "cash"
        BANK = "bank"
        MOBILE_MONEY = "mobile_money", "Mobile money"
        ONLINE_CLEARING = "online_clearing", "Online clearing"
        OTHER = "other"

    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="financial_accounts")
    name = models.CharField(max_length=120)
    account_type = models.CharField(max_length=30, choices=Type)
    currency = CurrencyField()
    provider_name = models.CharField(max_length=80, null=True, blank=True)
    account_reference_masked = models.CharField(max_length=100, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "financial_accounts"
        ordering = ["name"]

    def __str__(self):
        return self.name


class WebhookEvent(TimeStampedModel):
    """A payment-provider notification. Unique per provider event id, so retries are idempotent."""

    class Status(models.TextChoices):
        RECEIVED = "received"
        PROCESSING = "processing"
        PROCESSED = "processed"
        IGNORED = "ignored"
        FAILED = "failed"

    provider_name = models.CharField(max_length=80)
    provider_event_id = models.CharField(max_length=200)
    event_type = models.CharField(max_length=120)
    received_at = models.DateTimeField(default=timezone.now)
    signature_valid = models.BooleanField()
    processing_status = models.CharField(max_length=24, choices=Status, default=Status.RECEIVED)
    processed_at = models.DateTimeField(null=True, blank=True)
    payload_sha256 = models.CharField(max_length=64)
    # Only non-sensitive fields (reference, amount, currency, channel). Never the raw payload.
    safe_metadata = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "webhook_events"
        ordering = ["-received_at"]
        constraints = [
            models.UniqueConstraint(fields=["provider_name", "provider_event_id"], name="uq_webhook_event")
        ]
