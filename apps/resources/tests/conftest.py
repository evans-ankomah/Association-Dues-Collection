import datetime

import pytest
from django.utils import timezone

from apps.resources import services as svc


@pytest.fixture
def custodian(make_user, session):
    """Holds assets.manage."""
    return make_user("asset_custodian", session=session)


@pytest.fixture
def asset(department, custodian):
    return svc.create_asset(
        actor=custodian,
        department=department,
        asset_tag="CSE-PRJ-001",
        name="Epson Projector",
        asset_type="equipment",
        location="CSE Lab 1",
    )


@pytest.fixture
def slot():
    """A window starting tomorrow, so it is never in the past."""

    def _make(offset_hours=0, length_hours=2):
        start = timezone.now() + datetime.timedelta(days=1, hours=offset_hours)
        return start, start + datetime.timedelta(hours=length_hours)

    return _make
