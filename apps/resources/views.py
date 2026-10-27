from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.access.mixins import permission_required
from apps.access.services import has_perm
from apps.finance.views.common import paginate

from . import services
from .models import Asset, ResourceBooking
from .services import ResourceError

INPUT = {"class": "field-input"}
DATETIME = forms.DateTimeInput(attrs={**INPUT, "type": "datetime-local"}, format="%Y-%m-%dT%H:%M")


class AssetForm(forms.ModelForm):
    class Meta:
        model = Asset
        fields = [
            "asset_tag",
            "name",
            "asset_type",
            "description",
            "location",
            "condition_status",
            "availability_status",
            "acquired_on",
            "replacement_cost",
        ]
        labels = {
            "asset_tag": "Tag",
            "condition_status": "Condition",
            "availability_status": "Availability",
            "replacement_cost": "Replacement cost (GHS)",
        }
        widgets = {
            "asset_tag": forms.TextInput(attrs={**INPUT, "placeholder": "CSE-PRJ-001"}),
            "name": forms.TextInput(attrs=INPUT),
            "asset_type": forms.Select(attrs=INPUT),
            "description": forms.Textarea(attrs={**INPUT, "rows": 3}),
            "location": forms.TextInput(attrs=INPUT),
            "condition_status": forms.Select(attrs=INPUT),
            "availability_status": forms.Select(attrs=INPUT),
            "acquired_on": forms.DateInput(attrs={**INPUT, "type": "date"}, format="%Y-%m-%d"),
            "replacement_cost": forms.NumberInput(attrs={**INPUT, "step": "0.01", "min": "0"}),
        }


class BookingForm(forms.Form):
    starts_at = forms.DateTimeField(widget=DATETIME, label="From")
    ends_at = forms.DateTimeField(widget=DATETIME, label="Until")
    purpose = forms.CharField(widget=forms.Textarea(attrs={**INPUT, "rows": 3}), label="What for?")

    def clean(self):
        data = super().clean()
        if data.get("starts_at") and data.get("ends_at") and data["ends_at"] <= data["starts_at"]:
            self.add_error("ends_at", "Must be after the start.")
        return data


@login_required
def asset_list(request):
    """Members browse what can be booked; custodians see everything."""
    if request.department is None:
        raise PermissionDenied
    can_manage = has_perm(request.user, services.MANAGE, request.department)
    asset_type = request.GET.get("type", "")
    qs = Asset.objects.filter(department=request.department).select_related("custodian_user__profile")
    if not can_manage:
        qs = qs.exclude(availability_status=Asset.Availability.RETIRED)
    if asset_type:
        qs = qs.filter(asset_type=asset_type)
    page, query = paginate(request, qs, per_page=30)
    return render(
        request,
        "resources/asset_list.html",
        {
            "page": page,
            "query": query,
            "asset_type": asset_type,
            "types": Asset.Type.choices,
            "can_manage": can_manage,
            "summary": services.utilisation(request.department) if can_manage else None,
        },
    )


@login_required
def asset_detail(request, pk):
    asset = get_object_or_404(
        Asset.objects.select_related("custodian_user__profile"), pk=pk, department=request.department
    )
    can_manage = has_perm(request.user, services.MANAGE, request.department)
    return render(
        request,
        "resources/asset_detail.html",
        {
            "asset": asset,
            "form": BookingForm(),
            "bookings": services.bookings_for(request.department, asset=asset, upcoming_only=True).exclude(
                booking_status__in=(
                    ResourceBooking.Status.CANCELLED,
                    ResourceBooking.Status.REJECTED,
                )
            ),
            "can_manage": can_manage,
            "can_book": asset.is_bookable and has_perm(request.user, services.REQUEST, request.department),
        },
    )


@permission_required("assets.manage")
def asset_form(request, pk=None):
    asset = get_object_or_404(Asset, pk=pk, department=request.department) if pk else None
    form = AssetForm(request.POST or None, instance=asset)
    if request.method == "POST" and form.is_valid():
        if asset is None:
            saved = services.create_asset(
                actor=request.user,
                department=request.department,
                **{k: v for k, v in form.cleaned_data.items() if v not in (None, "")},
            )
        else:
            saved = services.update_asset(asset, actor=request.user, **form.cleaned_data)
        messages.success(request, "Asset saved.")
        return redirect("resources:asset", pk=saved.pk)
    return render(request, "resources/asset_form.html", {"form": form, "asset": asset})


@permission_required("requests.create", "assets.manage")
@require_POST
def book(request, pk):
    asset = get_object_or_404(Asset, pk=pk, department=request.department)
    form = BookingForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Check the dates and try again.")
        return redirect("resources:asset", pk=pk)
    data = form.cleaned_data
    try:
        services.request_booking(
            asset,
            actor=request.user,
            starts_at=data["starts_at"],
            ends_at=data["ends_at"],
            purpose=data["purpose"],
        )
        messages.success(request, "Booking requested. A custodian will confirm it.")
    except ResourceError as exc:
        messages.error(request, str(exc))
    return redirect("resources:asset", pk=pk)


@login_required
def booking_list(request):
    if request.department is None:
        raise PermissionDenied
    can_manage = has_perm(request.user, services.MANAGE, request.department)
    status = request.GET.get("status", "")
    scope = request.GET.get("scope", "" if can_manage else "mine")
    qs = services.bookings_for(
        request.department,
        status=status,
        user=request.user if scope == "mine" or not can_manage else None,
    )
    page, query = paginate(request, qs.order_by("-starts_at"), per_page=30)
    return render(
        request,
        "resources/booking_list.html",
        {
            "page": page,
            "query": query,
            "status": status,
            "scope": "mine" if (scope == "mine" or not can_manage) else "",
            "statuses": ResourceBooking.Status.choices,
            "can_manage": can_manage,
            "now": timezone.now(),
        },
    )


@login_required
@require_POST
def booking_action(request, pk):
    booking = get_object_or_404(
        ResourceBooking.objects.select_related("asset"),
        pk=pk,
        asset__department=request.department,
    )
    action = request.POST.get("action")
    try:
        if action in ("approve", "reject"):
            services.decide_booking(
                booking,
                actor=request.user,
                approve=action == "approve",
                note=request.POST.get("note", ""),
            )
            messages.success(request, "Booking updated.")
        elif action == "check_out":
            services.check_out(booking, actor=request.user)
            messages.success(request, "Checked out.")
        elif action == "check_in":
            services.check_in(
                booking,
                actor=request.user,
                condition=request.POST.get("condition") or None,
                notes=request.POST.get("notes", ""),
            )
            messages.success(request, "Returned.")
        elif action == "cancel":
            services.cancel_booking(booking, actor=request.user)
            messages.success(request, "Booking cancelled.")
    except ResourceError as exc:
        messages.error(request, str(exc))
    return redirect(request.POST.get("next") or "resources:bookings")
