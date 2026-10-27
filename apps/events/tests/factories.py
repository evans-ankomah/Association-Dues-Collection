import datetime

import factory
from django.utils import timezone

from apps.events.models import Event


class EventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Event

    title = factory.Sequence(lambda n: f"Event {n}")
    event_type = "seminar"
    venue_text = "UMaT Auditorium"
    starts_at = factory.LazyFunction(lambda: timezone.now() + datetime.timedelta(days=7))
    ends_at = factory.LazyFunction(lambda: timezone.now() + datetime.timedelta(days=7, hours=3))
    registration_required = True
    event_status = Event.Status.PUBLISHED
    published_at = factory.LazyFunction(timezone.now)
