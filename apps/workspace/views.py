from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.access.mixins import permission_required
from apps.access.services import has_perm
from apps.audit.services import record, snapshot
from apps.documents.models import Document
from apps.events.models import Event
from apps.finance.views.common import paginate
from apps.memberships.models import DepartmentMembership

from . import services
from .models import Committee, CommitteeMember, Meeting, Task
from .services import WorkspaceError

INPUT = {"class": "field-input"}
DATETIME = forms.DateTimeInput(attrs={**INPUT, "type": "datetime-local"}, format="%Y-%m-%dT%H:%M")


class CommitteeForm(forms.ModelForm):
    class Meta:
        model = Committee
        fields = ["name", "description", "chair_membership"]
        labels = {"chair_membership": "Chair"}
        widgets = {
            "name": forms.TextInput(attrs=INPUT),
            "description": forms.Textarea(attrs={**INPUT, "rows": 3}),
            "chair_membership": forms.Select(attrs=INPUT),
        }

    def __init__(self, *args, department=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["chair_membership"].queryset = DepartmentMembership.objects.filter(
            department=department, membership_status=DepartmentMembership.Status.ACTIVE
        ).select_related("user__profile")
        self.fields["chair_membership"].required = False


class MeetingForm(forms.ModelForm):
    class Meta:
        model = Meeting
        fields = ["title", "committee", "scheduled_at", "location_text"]
        labels = {"scheduled_at": "When", "location_text": "Where"}
        widgets = {
            "title": forms.TextInput(attrs=INPUT),
            "committee": forms.Select(attrs=INPUT),
            "scheduled_at": DATETIME,
            "location_text": forms.TextInput(attrs=INPUT),
        }

    def __init__(self, *args, department=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["committee"].queryset = Committee.objects.filter(
            department=department, committee_status=Committee.Status.ACTIVE
        )
        self.fields["committee"].required = False


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = [
            "title",
            "description",
            "priority",
            "assigned_to_user",
            "committee",
            "event",
            "due_at",
        ]
        labels = {"assigned_to_user": "Owner", "due_at": "Due"}
        widgets = {
            "title": forms.TextInput(attrs=INPUT),
            "description": forms.Textarea(attrs={**INPUT, "rows": 3}),
            "priority": forms.Select(attrs=INPUT),
            "assigned_to_user": forms.Select(attrs=INPUT),
            "committee": forms.Select(attrs=INPUT),
            "event": forms.Select(attrs=INPUT),
            "due_at": DATETIME,
        }

    def __init__(self, *args, department=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.accounts.models import User

        member_ids = DepartmentMembership.objects.filter(
            department=department, membership_status=DepartmentMembership.Status.ACTIVE
        ).values("user_id")
        self.fields["assigned_to_user"].queryset = User.objects.filter(
            pk__in=member_ids, is_active=True
        ).select_related("profile")
        self.fields["committee"].queryset = Committee.objects.filter(
            department=department, committee_status=Committee.Status.ACTIVE
        )
        self.fields["event"].queryset = Event.objects.filter(department=department)
        for name in ("assigned_to_user", "committee", "event", "due_at"):
            self.fields[name].required = False


# --- committees -------------------------------------------------------------------------------


@permission_required("committees.manage")
def committee_list(request):
    qs = Committee.objects.filter(
        department=request.department, academic_session=request.academic_session
    ).select_related("chair_membership__user__profile")
    return render(request, "workspace/committee_list.html", {"committees": qs})


@permission_required("committees.manage")
def committee_detail(request, pk):
    committee = get_object_or_404(
        Committee.objects.select_related("chair_membership__user__profile"),
        pk=pk,
        department=request.department,
    )
    return render(
        request,
        "workspace/committee_detail.html",
        {
            "committee": committee,
            "members": committee.members.select_related("department_membership__user__profile"),
            "meetings": committee.meetings.all()[:10],
            "tasks": services.task_board(request.department, committee=committee)[:20],
            "candidates": DepartmentMembership.objects.filter(
                department=request.department,
                membership_status=DepartmentMembership.Status.ACTIVE,
            ).select_related("user__profile"),
        },
    )


@permission_required("committees.manage")
def committee_form(request, pk=None):
    committee = get_object_or_404(Committee, pk=pk, department=request.department) if pk else None
    form = CommitteeForm(request.POST or None, instance=committee, department=request.department)
    if request.method == "POST" and form.is_valid():
        try:
            if committee is None:
                saved = services.create_committee(
                    actor=request.user,
                    department=request.department,
                    academic_session=request.academic_session,
                    name=form.cleaned_data["name"],
                    description=form.cleaned_data["description"] or "",
                    chair=form.cleaned_data["chair_membership"],
                )
            else:
                saved = form.save()
            messages.success(request, "Committee saved.")
            return redirect("workspace:committee", pk=saved.pk)
        except WorkspaceError as exc:
            messages.error(request, str(exc))
    return render(request, "workspace/committee_form.html", {"form": form, "committee": committee})


@permission_required("committees.manage")
@require_POST
def committee_action(request, pk):
    committee = get_object_or_404(Committee, pk=pk, department=request.department)
    action = request.POST.get("action")
    try:
        if action == "add_member":
            membership = get_object_or_404(
                DepartmentMembership,
                pk=request.POST.get("membership"),
                department=request.department,
            )
            services.add_member(
                committee,
                actor=request.user,
                membership=membership,
                role_title=request.POST.get("role_title") or None,
            )
            messages.success(request, "Member added.")
        elif action == "end_member":
            seat = get_object_or_404(CommitteeMember, pk=request.POST.get("seat"), committee=committee)
            services.end_membership(seat, actor=request.user)
            messages.success(request, "Seat ended.")
        elif action in ("archived", "inactive", "active"):
            services.set_committee_status(committee, actor=request.user, status=action)
            messages.success(request, "Committee updated.")
    except WorkspaceError as exc:
        messages.error(request, str(exc))
    return redirect("workspace:committee", pk=pk)


# --- meetings ---------------------------------------------------------------------------------


@permission_required("committees.manage")
def meeting_list(request):
    qs = Meeting.objects.filter(department=request.department).select_related("committee")
    page, query = paginate(request, qs, per_page=30)
    return render(request, "workspace/meeting_list.html", {"page": page, "query": query})


@permission_required("committees.manage")
def meeting_detail(request, pk):
    meeting = get_object_or_404(
        Meeting.objects.select_related("committee", "minutes_document"),
        pk=pk,
        department=request.department,
    )
    return render(
        request,
        "workspace/meeting_detail.html",
        {
            "meeting": meeting,
            "tasks": services.task_board(request.department).filter(meeting=meeting),
            "minutes_choices": Document.objects.filter(
                department=request.department, category="minutes"
            ).current(),
        },
    )


@permission_required("committees.manage")
def meeting_form(request, pk=None):
    meeting = get_object_or_404(Meeting, pk=pk, department=request.department) if pk else None
    form = MeetingForm(request.POST or None, instance=meeting, department=request.department)
    if request.method == "POST" and form.is_valid():
        try:
            if meeting is None:
                saved = services.schedule_meeting(
                    actor=request.user,
                    department=request.department,
                    title=form.cleaned_data["title"],
                    scheduled_at=form.cleaned_data["scheduled_at"],
                    committee=form.cleaned_data["committee"],
                    location_text=form.cleaned_data["location_text"],
                )
            else:
                saved = form.save()
            messages.success(request, "Meeting saved.")
            return redirect("workspace:meeting", pk=saved.pk)
        except WorkspaceError as exc:
            messages.error(request, str(exc))
    return render(request, "workspace/meeting_form.html", {"form": form, "meeting": meeting})


@permission_required("committees.manage")
@require_POST
def meeting_action(request, pk):
    meeting = get_object_or_404(Meeting, pk=pk, department=request.department)
    action = request.POST.get("action")
    try:
        if action == "minutes":
            document = get_object_or_404(
                Document, pk=request.POST.get("document"), department=request.department
            )
            services.attach_minutes(meeting, actor=request.user, document=document)
            messages.success(request, "Minutes attached.")
        elif action in ("held", "cancelled", "scheduled"):
            services.set_meeting_status(meeting, actor=request.user, status=action)
            messages.success(request, "Meeting updated.")
    except WorkspaceError as exc:
        messages.error(request, str(exc))
    return redirect("workspace:meeting", pk=pk)


# --- tasks ------------------------------------------------------------------------------------


@login_required
def task_list(request):
    """Everyone sees their own tasks; committees.manage sees the whole board."""
    if request.department is None:
        raise PermissionDenied
    is_manager = has_perm(request.user, services.MANAGE, request.department)
    status = request.GET.get("status", "")
    scope = request.GET.get("scope", "mine" if not is_manager else "")
    if scope == "mine" or not is_manager:
        qs = services.my_tasks(request.user, request.department).select_related(
            "committee", "event", "assigned_to_user__profile"
        )
        scope = "mine"
        if status:
            qs = qs.filter(task_status=status)
    else:
        qs = services.task_board(request.department, status=status)
    page, query = paginate(request, qs, per_page=30)
    return render(
        request,
        "workspace/task_list.html",
        {
            "page": page,
            "query": query,
            "status": status,
            "scope": scope,
            "statuses": Task.Status.choices,
            "is_manager": is_manager,
            "summary": services.workspace_summary(request.department, session=request.academic_session)
            if is_manager
            else None,
        },
    )


@permission_required("committees.manage")
def task_form(request, pk=None):
    task = get_object_or_404(Task, pk=pk, department=request.department) if pk else None
    form = TaskForm(request.POST or None, instance=task, department=request.department)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            if task is None:
                services.create_task(
                    actor=request.user,
                    department=request.department,
                    title=data["title"],
                    description=data["description"] or "",
                    priority=data["priority"],
                    assignee=data["assigned_to_user"],
                    committee=data["committee"],
                    event=data["event"],
                    due_at=data["due_at"],
                )
            else:
                saved = form.save()
                record(
                    "task.updated",
                    saved,
                    actor=request.user,
                    department=request.department,
                    after=snapshot(saved, fields=["title", "task_status", "priority", "due_at"]),
                )
            messages.success(request, "Task saved.")
            return redirect("workspace:tasks")
        except WorkspaceError as exc:
            messages.error(request, str(exc))
    return render(request, "workspace/task_form.html", {"form": form, "task": task})


@login_required
@require_POST
def task_action(request, pk):
    task = get_object_or_404(Task, pk=pk, department=request.department)
    action = request.POST.get("action")
    try:
        if action == "status":
            services.set_task_status(task, actor=request.user, status=request.POST.get("status"))
            messages.success(request, "Task updated.")
        elif action == "assign":
            from apps.accounts.models import User

            assignee = (
                get_object_or_404(User, pk=request.POST["assignee"]) if request.POST.get("assignee") else None
            )
            services.assign_task(task, actor=request.user, assignee=assignee)
            messages.success(request, "Task reassigned.")
    except WorkspaceError as exc:
        messages.error(request, str(exc))
    return redirect(request.POST.get("next") or "workspace:tasks")
