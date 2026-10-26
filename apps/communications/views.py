from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.access.mixins import permission_required
from apps.access.services import has_perm
from apps.audit.services import record, snapshot
from apps.finance.views.common import paginate
from apps.memberships.models import DepartmentMembership

from . import services
from .delivery import mark_read
from .forms import AnnouncementForm
from .models import Announcement, AnnouncementAcknowledgement, Notification


@permission_required("announcements.view", "announcements.publish")
def announcement_list(request):
    search = request.GET.get("q", "").strip()
    qs = services.visible_announcements(request.user, request.department).order_by("-published_at")
    if search:
        qs = qs.filter(Q(title__icontains=search) | Q(body__icontains=search))
    page, query = paginate(request, qs, per_page=20)
    acknowledged = set(
        AnnouncementAcknowledgement.objects.filter(user=request.user, announcement__in=page).values_list(
            "announcement_id", flat=True
        )
    )
    return render(
        request,
        "communications/announcement_list.html",
        {
            "page": page,
            "query": query,
            "search": search,
            "acknowledged": acknowledged,
            "can_publish": has_perm(request.user, "announcements.publish", request.department),
        },
    )


@permission_required("announcements.view", "announcements.publish")
def announcement_detail(request, pk):
    announcement = get_object_or_404(Announcement, pk=pk, department=request.department)
    can_publish = has_perm(request.user, "announcements.publish", request.department)
    if not can_publish and not services.can_view(request.user, announcement):
        raise PermissionDenied
    return render(
        request,
        "communications/announcement_detail.html",
        {
            "announcement": announcement,
            "can_publish": can_publish,
            "acknowledged": AnnouncementAcknowledgement.objects.filter(
                announcement=announcement, user=request.user
            ).first(),
            "stats": services.acknowledgement_stats(announcement) if can_publish else None,
        },
    )


@permission_required("announcements.view", "announcements.publish")
@require_POST
def acknowledge(request, pk):
    announcement = get_object_or_404(Announcement, pk=pk, department=request.department)
    if not services.can_view(request.user, announcement):
        raise PermissionDenied
    services.acknowledge(request.user, announcement)
    messages.success(request, "Thanks for confirming you've read this.")
    return redirect("communications:announcement", pk=pk)


@permission_required("announcements.publish")
def manage(request):
    status = request.GET.get("status", "")
    qs = Announcement.objects.filter(department=request.department).select_related("created_by__profile")
    if status:
        qs = qs.filter(announcement_status=status)
    page, query = paginate(request, qs.order_by("-created_at"), per_page=30)
    return render(
        request,
        "communications/manage.html",
        {"page": page, "query": query, "status": status, "statuses": Announcement.Status.choices},
    )


def _choices(department, session):
    members = DepartmentMembership.objects.filter(department=department, academic_session=session)
    levels = sorted({v for v in members.values_list("level_code", flat=True) if v})
    programmes = sorted({v for v in members.values_list("programme_name", flat=True) if v})
    return levels, programmes


@permission_required("announcements.publish")
def edit(request, pk=None):
    announcement = (
        get_object_or_404(Announcement, pk=pk, department=request.department) if pk else Announcement()
    )
    if pk and announcement.announcement_status not in (
        Announcement.Status.DRAFT,
        Announcement.Status.SCHEDULED,
    ):
        messages.error(request, "Published notices can't be edited. Archive it and post a correction.")
        return redirect("communications:announcement", pk=pk)
    levels, programmes = _choices(request.department, request.academic_session)
    form = AnnouncementForm(
        request.POST or None, instance=announcement, level_choices=levels, programme_choices=programmes
    )
    if request.method == "POST" and form.is_valid():
        before = snapshot(announcement) if pk else None
        announcement = form.save(commit=False)
        if not pk:
            announcement.department = request.department
            announcement.created_by = request.user
        announcement.save()
        record(
            "announcement.saved",
            announcement,
            actor=request.user,
            department=request.department,
            before=before,
            after=snapshot(announcement),
        )
        if "publish" in request.POST:
            services.publish(announcement, actor=request.user, at=form.cleaned_data.get("publish_at"))
            verb = "scheduled" if announcement.announcement_status == "scheduled" else "published"
            messages.success(request, f"Notice {verb}.")
        else:
            messages.success(request, "Draft saved.")
        return redirect("communications:announcement", pk=announcement.pk)
    return render(
        request, "communications/announcement_form.html", {"form": form, "announcement": announcement}
    )


@permission_required("announcements.publish")
@require_POST
def change_status(request, pk):
    announcement = get_object_or_404(Announcement, pk=pk, department=request.department)
    status = request.POST.get("status")
    allowed = {
        Announcement.Status.PUBLISHED: {Announcement.Status.ARCHIVED},
        Announcement.Status.SCHEDULED: {Announcement.Status.CANCELLED},
        Announcement.Status.DRAFT: {Announcement.Status.CANCELLED},
    }
    if status not in allowed.get(announcement.announcement_status, set()):
        messages.error(request, "That change isn't allowed.")
    else:
        services.set_status(announcement, actor=request.user, status=status)
        messages.success(request, f"Notice {status}.")
    return redirect("communications:announcement", pk=pk)


def _in_app(request):
    return Notification.objects.filter(user=request.user, channel=Notification.Channel.IN_APP)


@login_required
def notification_list(request):
    page, query = paginate(request, _in_app(request).order_by("-created_at"), per_page=30)
    return render(request, "communications/notification_list.html", {"page": page, "query": query})


@login_required
def open_notification(request, pk):
    notification = get_object_or_404(_in_app(request), pk=pk)
    mark_read(request.user, [notification.pk])
    target = notification.link or "/communications/notifications/"
    if not url_has_allowed_host_and_scheme(target, {request.get_host()}):
        target = "/"
    return redirect(target)


@login_required
@require_POST
def mark_all_read(request):
    mark_read(request.user)
    if request.htmx:
        return bell(request)
    return redirect("communications:notifications")


@login_required
def bell(request):
    unread = _in_app(request).filter(read_at__isnull=True)
    return render(
        request,
        "communications/partials/bell.html",
        {"unread_count": unread.count(), "recent": _in_app(request).order_by("-created_at")[:6]},
    )
