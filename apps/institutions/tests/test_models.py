import datetime

import pytest
from django.db import IntegrityError

from apps.common.tests.factories import AcademicSessionFactory, InstitutionFactory

pytestmark = pytest.mark.django_db


def test_only_one_current_session_per_institution():
    institution = InstitutionFactory()
    AcademicSessionFactory(institution=institution, is_current=True)
    with pytest.raises(IntegrityError):
        AcademicSessionFactory(institution=institution, is_current=True)


def test_session_end_cannot_precede_start():
    with pytest.raises(IntegrityError):
        AcademicSessionFactory(starts_on=datetime.date(2026, 9, 1), ends_on=datetime.date(2026, 8, 1))
