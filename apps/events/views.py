from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.access.mixins import permission_required
from apps.access.services import has_perm
from apps.audit.services import record, snapshot
from apps.finance.models import Budget
from apps.finance.views.common import paginate
from apps.memberships.models import DepartmentMembership

from . import services
from .models import Event, EventAttendance, EventRegistration
from .services import EventError

INPUT = {"class": "field-input"}
DATETIME = forms.DateTimeInput(attrs={**INPUT, "type": "datetime-local"}, format="%Y-%m-%dT%H:%M")

EVENT_TYPES = [
    ("orientation", "Orientation"),
    ("seminar", "Seminar"),
    ("workshop", "Workshop"),
    ("hackathon", "Hackathon"),
    ("departmental_week", "Departmental week"),
    ("sports", "Sports"),
    ("excursion", "Excursion"),
    ("social", "Social"),
    ("meeting", "Meeting"),
    ("other", "Other"),
]


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = [
            "title",
            "event_type",
            "description",
            "venue_text",
            "starts_at",
            "ends_at",
            "capacity",
            "registration_required",
            "related_budget",
        ]
        labels = {
            "venue_text": "Venue",
            "starts_at": "Starts",
            "ends_at": "Ends",
            "registration_required": "Members must register",
            "related_budget": "Budget",
        }
        help_texts = {"capacity": "Leave blank for no limit. Members beyond it are waitlisted."}
        widgets = {
            "title": forms.TextInput(attrs=INPUT),
            "event_type": forms.Select(attrs=INPUT, choices=EVENT_TYPES),
            "description": forms.Textarea(attrs={**INPUT, "rows": 4}),
            "venue_text": forms.TextInput(attrs=INPUT),
            "starts_at": DATETIME,
            "ends_at": DATETIME,
            "capacity": forms.NumberInput(attrs={**INPUT, "min": "1"}),
            "registration_required": forms.CheckboxInput(),
            "related_budget": forms.Select(attrs=INPUT),
        }

    def __init__(self, *args, department=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["related_budget"].queryset = Budget.objects.filter(
            department=department, budget_status=Budget.Status.APPROVED
        )
        self.fields["related_budget"].required = False

    def clean(self):
        data = super().clean()
        if data.get("starts_at") and data.get("ends_at") and data["ends_at"] < data["starts_at"]:
            self.add_error("ends_at", "Must be on or after the start.")
        return data


@login_required
def event_list(request):
    """Everyone sees published events; organisers also see drafts and pending approvals."""
    if request.department is None:
        raise PermissionDenied
    show = request.GET.get("show", "upcoming")
    qs = services.visible_events(request.user, request.department).select_related("related_budget")
    if show == "upcoming":
        qs = qs.upcoming().order_by("starts_at")
    elif show == "past":
        qs = qs.filter(ends_at__lt=timezone.now())
    page, query = paginate(request, qs, per_page=20)
    my_event_ids = set(
        EventRegistration.objects.filter(
            department_membership__user=request.user,
            event__in=[e.pk for e in page],
        )
        .exclude(registration_status=EventRegistration.Status.CANCELLED)
        .values_list("event_id", flat=True)
    )
    return render(
        request,
        "events/event_list.html",
        {
            "page": page,
            "query": query,
            "show": show,
            "my_event_ids": my_event_ids,
            "can_manage": has_perm(request.user, services.MANAGE, request.department),
        },
    )


@login_required
def event_detail(request, pk):
    event = get_object_or_404(
        Event.objects.select_related("related_budget", "created_by__profile"),
        pk=pk,
        department=request.department,
    )
    can_manage = has_perm(request.user, services.MANAGE, request.department)
    if not can_manage and not services.can_view(request.user, event):
        raise PermissionDenied
    my_registration = (
        EventRegistration.objects.filter(event=event, department_membership__user=request.user)
        .exclude(registration_status=EventRegistration.Status.CANCELLED)
        .first()
    )
    return render(
        request,
        "events/event_detail.html",
        {
            "event": event,
            "summary": services.attendance_summary(event) if can_manage else None,
            "my_registration": my_registration,
            "can_manage": can_manage,
            "can_register": (
                my_registration is None
                and event.is_open_for_registration
                and has_perm(request.user, services.REGISTER, request.department)
            ),
            "can_publish": can_manage
            and event.event_status in (Event.Status.DRAFT, Event.Status.PENDING_APPROVAL),
            "can_edit": can_manage
            and event.event_status in (Event.Status.DRAFT, Event.Status.PENDING_APPROVAL),
            "can_complete": can_manage
            and event.event_status == Event.Status.PUBLISHED
            and event.ends_at < timezone.now(),
        },
    )


@permission_required("events.manage")
def event_form(request, pk=None):
    event = get_object_or_404(Event, pk=pk, department=request.department) if pk else None
    if event and event.event_status not in (Event.Status.DRAFT, Event.Status.PENDING_APPROVAL):
        messages.error(request, "Only a draft or pending event can be edited.")
        return redirect("events:detail", pk=pk)
    form = EventForm(request.POST or None, instance=event, department=request.department)
    if request.method == "POST" and form.is_valid():
        before = snapshot(event) if event else None
        saved = form.save(commit=False)
        if event is None:
            saved.department = request.department
            saved.created_by = request.user
        saved.save()
        record(
            "event.saved",
            saved,
            actor=request.user,
            department=request.department,
            before=before,
            after=snapshot(saved),
        )
        if "publish" in request.POST:
            try:
                services.publish(saved, actor=request.user)
                messages.success(request, "Event published.")
            except EventError as exc:
                messages.error(request, str(exc))
        else:
            messages.success(request, "Event saved.")
        return redirect("events:detail", pk=saved.pk)
    return render(request, "events/event_form.html", {"form": form, "event": event})


@permission_required("events.manage")
@require_POST
def event_action(request, pk):
    event = get_object_or_404(Event, pk=pk, department=request.department)
    action = request.POST.get("action")
    try:
        if action == "publish":
            services.publish(event, actor=request.user)
        elif action in ("cancelled", "draft"):
            services.set_status(event, actor=request.user, status=action)
        elif action == "complete":
            services.close_registrations(event, actor=request.user)
        messages.success(request, "Event updated.")
    except EventError as exc:
        messages.error(request, str(exc))
    return redirect("events:detail", pk=pk)


@permission_required("events.register", "events.manage")
@require_POST
def register(request, pk):
    """A member takes a seat for themselves."""
    event = get_object_or_404(Event, pk=pk, department=request.department)
    if not services.can_view(request.user, event):
        raise PermissionDenied
    try:
        registration = services.register(event, actor=request.user)
        messages.success(
            request,
            "You're on the waiting list — we'll move you up if a seat frees."
            if registration.registration_status == EventRegistration.Status.WAITLISTED
            else "You're registered.",
        )
    except EventError as exc:
        messages.error(request, str(exc))
    return redirect("events:detail", pk=pk)


@permission_required("events.register", "events.manage")
@require_POST
def cancel_registration(request, pk):
    registration = get_object_or_404(EventRegistration, pk=pk, event__department=request.department)
    try:
        services.cancel_registration(registration, actor=request.user)
        messages.success(request, "Registration cancelled.")
    except EventError as exc:
        messages.error(request, str(exc))
    return redirect("events:detail", pk=registration.event_id)


@permission_required("events.manage")
def attendance(request, pk):
    """Registration and attendance lists for the organisers."""
    event = get_object_or_404(Event, pk=pk, department=request.department)
    registrations = EventRegistration.objects.filter(event=event).select_related(
        "department_membership__user__profile"
    )
    recorded = EventAttendance.objects.filter(event=event).select_related(
        "department_membership__user__profile"
    )
    return render(
        request,
        "events/attendance.html",
        {
            "event": event,
            "registrations": registrations,
            "attendance": recorded,
            "summary": services.attendance_summary(event),
        },
    )


@permission_required("events.manage")
@require_POST
def check_in(request, pk):
    event = get_object_or_404(Event, pk=pk, department=request.department)
    membership = get_object_or_404(
        DepartmentMembership, pk=request.POST.get("membership"), department=request.department
    )
    try:
        services.check_in(
            event,
            actor=request.user,
            membership=membership,
            status=request.POST.get("status") or EventAttendance.Status.PRESENT,
            method=EventAttendance.Method.MANUAL,
        )
        messages.success(request, "Attendance recorded.")
    except EventError as exc:
        messages.error(request, str(exc))
    return redirect("events:attendance", pk=pk)


@permission_required("events.manage")
def member_search(request, pk):
    """HTMX: members of this department matching a name, email or student number, for check-in."""
    event = get_object_or_404(Event, pk=pk, department=request.department)
    term = request.GET.get("q", "").strip()
    results = []
    if len(term) >= 2:
        results = (
            DepartmentMembership.objects.filter(department=request.department)
            .filter(membership_status=DepartmentMembership.Status.ACTIVE)
            .select_related("user__profile")
            .filter(
                Q(user__profile__given_name__icontains=term)
                | Q(user__profile__family_name__icontains=term)
                | Q(user__email__icontains=term)
                | Q(user__profile__student_number__icontains=term)
            )[:10]
        )
    checked_in = set(
        EventAttendance.objects.filter(event=event).values_list("department_membership_id", flat=True)
    )
    return render(
        request,
        "events/partials/member_results.html",
        {"event": event, "results": results, "term": term, "checked_in": checked_in},
    )
