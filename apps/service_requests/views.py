from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.access.mixins import permission_required
from apps.access.models import RoleAssignment
from apps.access.services import has_perm
from apps.accounts.models import User
from apps.finance.views.common import paginate

from . import services
from .models import REQUEST_TYPES, SENSITIVE_TYPES, ServiceRequest
from .services import ServiceRequestError

INPUT = {"class": "field-input"}


class ServiceRequestForm(forms.ModelForm):
    class Meta:
        model = ServiceRequest
        fields = ["request_type", "title", "description", "priority", "visibility_level"]
        labels = {
            "request_type": "What do you need?",
            "title": "Subject",
            "description": "Details",
            "visibility_level": "Who can see this",
        }
        help_texts = {
            "visibility_level": "Private welfare and result queries are always kept private.",
            "description": "Include anything that helps whoever picks this up.",
        }
        widgets = {
            "request_type": forms.Select(attrs={**INPUT, "x-model": "kind"}, choices=REQUEST_TYPES),
            "title": forms.TextInput(attrs=INPUT),
            "description": forms.Textarea(attrs={**INPUT, "rows": 5}),
            "priority": forms.Select(attrs=INPUT),
            "visibility_level": forms.Select(attrs=INPUT),
        }


def _officer_choices(department):
    """Users who may be assigned requests in this department."""
    user_ids = (
        RoleAssignment.objects.current()
        .filter(department=department, role__grants__permission__permission_code=services.MANAGE)
        .values_list("user_id", flat=True)
    )
    return User.objects.filter(pk__in=user_ids, is_active=True).select_related("profile")


@login_required
def request_list(request):
    """My requests, plus the officer queue for anyone holding requests.manage."""
    if request.department is None:
        raise PermissionDenied
    status = request.GET.get("status", "")
    scope = request.GET.get("scope", "")
    is_officer = has_perm(request.user, services.MANAGE, request.department)
    if scope == "mine" or not is_officer:
        qs = services.visible_requests(request.user, request.department).filter(
            requester_membership__user=request.user
        )
        qs = qs.select_related("assigned_to_user__profile")
        scope = "mine"
    else:
        qs = services.queue_for(
            request.user, request.department, status=status, mine_only=scope == "assigned"
        )
    if status and scope == "mine":
        qs = qs.filter(request_status=status)
    page, query = paginate(request, qs, per_page=30)
    return render(
        request,
        "service_requests/request_list.html",
        {
            "page": page,
            "query": query,
            "status": status,
            "scope": scope,
            "statuses": ServiceRequest.Status.choices,
            "is_officer": is_officer,
            "can_create": has_perm(request.user, services.CREATE, request.department),
        },
    )


@login_required
def request_detail(request, pk):
    service_request = get_object_or_404(
        ServiceRequest.objects.select_related(
            "requester_membership__user__profile", "assigned_to_user__profile"
        ),
        pk=pk,
        department=request.department,
    )
    # A restricted request is invisible to everyone but its requester and assignee.
    if not services.can_view(request.user, service_request):
        raise PermissionDenied
    is_officer = services.is_handling_officer(request.user, service_request)
    is_requester = service_request.requester_user_id == request.user.pk
    return render(
        request,
        "service_requests/request_detail.html",
        {
            "req": service_request,
            "comments": services.visible_comments(request.user, service_request),
            "is_officer": is_officer,
            "is_requester": is_requester,
            "officers": _officer_choices(request.department) if is_officer else [],
            "statuses": ServiceRequest.Status.choices,
            "can_close": (is_requester or is_officer)
            and service_request.request_status
            in (ServiceRequest.Status.RESOLVED, ServiceRequest.Status.REJECTED),
        },
    )


@permission_required("requests.create")
def request_form(request):
    form = ServiceRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            service_request = services.submit(
                actor=request.user,
                department=request.department,
                request_type=data["request_type"],
                title=data["title"],
                description=data["description"],
                priority=data["priority"],
                visibility=data["visibility_level"],
            )
            if service_request.is_restricted and data["request_type"] in SENSITIVE_TYPES:
                messages.success(
                    request, "Request submitted. It's been kept private to you and the officer handling it."
                )
            else:
                messages.success(request, "Request submitted.")
            return redirect("service_requests:detail", pk=service_request.pk)
        except ServiceRequestError as exc:
            messages.error(request, str(exc))
    return render(request, "service_requests/request_form.html", {"form": form})


@login_required
@require_POST
def request_action(request, pk):
    service_request = get_object_or_404(ServiceRequest, pk=pk, department=request.department)
    if not services.can_view(request.user, service_request):
        raise PermissionDenied
    action = request.POST.get("action")
    try:
        if action == "comment":
            services.comment(
                service_request,
                actor=request.user,
                body=request.POST.get("body", ""),
                staff_only=request.POST.get("staff_only") == "on",
            )
            messages.success(request, "Comment added.")
        elif action == "assign":
            assignee = (
                get_object_or_404(User, pk=request.POST["assignee"]) if request.POST.get("assignee") else None
            )
            services.assign(service_request, actor=request.user, assignee=assignee)
            messages.success(request, "Request assigned.")
        elif action == "status":
            services.set_status(
                service_request,
                actor=request.user,
                status=request.POST.get("status"),
                summary=request.POST.get("summary", ""),
            )
            messages.success(request, "Request updated.")
        elif action == "close":
            services.close(service_request, actor=request.user)
            messages.success(request, "Request closed.")
    except ServiceRequestError as exc:
        messages.error(request, str(exc))
    return redirect("service_requests:detail", pk=pk)
