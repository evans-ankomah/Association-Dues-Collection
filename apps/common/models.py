import uuid
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


class TimeStampedModel(models.Model):
    """UUID primary key plus created/updated timestamps, as every DeptHub table has."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class MoneyField(models.DecimalField):
    """numeric(12,2). Never use FloatField for money."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_digits", 12)
        kwargs.setdefault("decimal_places", 2)
        kwargs.setdefault("validators", [MinValueValidator(ZERO)])
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        for key, default in (("max_digits", 12), ("decimal_places", 2)):
            if kwargs.get(key) == default:
                kwargs.pop(key)
        kwargs.pop("validators", None)
        return name, path, args, kwargs


class CurrencyField(models.CharField):
    """ISO 4217 currency code."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_length", 3)
        kwargs.setdefault("default", "GHS")
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if kwargs.get("max_length") == 3:
            kwargs.pop("max_length")
        if kwargs.get("default") == "GHS":
            kwargs.pop("default")
        return name, path, args, kwargs
