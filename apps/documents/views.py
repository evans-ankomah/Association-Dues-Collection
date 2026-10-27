from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.access.mixins import permission_required
from apps.access.services import has_perm
from apps.finance.views.common import paginate

from . import services, storage
from .models import CATEGORIES, Document
from .services import DocumentError

INPUT = {"class": "field-input"}


class DocumentForm(forms.Form):
    title = forms.CharField(max_length=180, widget=forms.TextInput(attrs=INPUT))
    category = forms.ChoiceField(choices=CATEGORIES, widget=forms.Select(attrs=INPUT))
    visibility = forms.ChoiceField(
        choices=Document.Visibility.choices,
        initial=Document.Visibility.DEPARTMENT,
        widget=forms.Select(attrs=INPUT),
        label="Who can read it",
        help_text="Minutes and financial evidence are usually department-only.",
    )
    upload = forms.FileField(widget=forms.ClearableFileInput(attrs={"class": "field-input"}), label="File")


@permission_required("committees.manage")
def document_list(request):
    category = request.GET.get("category", "")
    qs = services.readable_documents(request.user, request.department).select_related("uploaded_by__profile")
    if category:
        qs = qs.filter(category=category)
    if request.GET.get("versions") != "all":
        qs = qs.current()
    page, query = paginate(request, qs.order_by("-uploaded_at"), per_page=30)
    return render(
        request,
        "documents/document_list.html",
        {
            "page": page,
            "query": query,
            "category": category,
            "categories": CATEGORIES,
            "show_all_versions": request.GET.get("versions") == "all",
        },
    )


@permission_required("committees.manage")
def document_detail(request, pk):
    document = get_object_or_404(
        Document.objects.select_related("uploaded_by__profile"), pk=pk, department=request.department
    )
    if not services.can_read(request.user, document):
        raise PermissionDenied
    return render(
        request,
        "documents/document_detail.html",
        {
            "document": document,
            "versions": services.version_history(document),
            "can_edit": services.can_edit(request.user, document),
            "can_review": (
                has_perm(request.user, services.REVIEW, request.department)
                and document.uploaded_by_id != request.user.pk
                and document.review_status == Document.ReviewStatus.PENDING_REVIEW
            ),
            "visibilities": Document.Visibility.choices,
        },
    )


@permission_required("committees.manage")
def document_upload(request):
    replaces = None
    if request.GET.get("replaces"):
        replaces = get_object_or_404(Document, pk=request.GET["replaces"], department=request.department)
    form = DocumentForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            document = services.upload(
                actor=request.user,
                department=request.department,
                upload_file=data["upload"],
                title=data["title"],
                category=data["category"],
                visibility=data["visibility"],
                replaces=replaces,
            )
            messages.success(request, "Document uploaded.")
            return redirect("documents:detail", pk=document.pk)
        except DocumentError as exc:
            messages.error(request, str(exc))
    return render(request, "documents/document_form.html", {"form": form, "replaces": replaces})


@permission_required("committees.manage")
def download(request, pk):
    """The only way to read a stored file. Permissions are checked before any bytes are read."""
    document = get_object_or_404(Document, pk=pk, department=request.department)
    if not services.can_read(request.user, document):
        raise PermissionDenied
    services.record_download(document, actor=request.user)
    response = FileResponse(
        storage.open_file(document.storage_key),
        as_attachment=True,
        filename=document.original_filename,
        content_type=document.mime_type,
    )
    # Private file: never cached by a proxy, never sniffed into something executable.
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@permission_required("committees.manage")
@require_POST
def document_action(request, pk):
    document = get_object_or_404(Document, pk=pk, department=request.department)
    if not services.can_read(request.user, document):
        raise PermissionDenied
    action = request.POST.get("action")
    try:
        if action == "visibility":
            services.set_visibility(document, actor=request.user, visibility=request.POST.get("visibility"))
            messages.success(request, "Visibility updated.")
        elif action == "submit":
            services.submit_for_review(document, actor=request.user)
            messages.success(request, "Sent for review.")
        elif action in ("approve", "reject"):
            services.review(
                document,
                actor=request.user,
                approve=action == "approve",
                note=request.POST.get("note", ""),
            )
            messages.success(request, "Review recorded.")
        elif action == "archive":
            services.archive(document, actor=request.user)
            messages.success(request, "Document archived.")
    except DocumentError as exc:
        messages.error(request, str(exc))
    return redirect("documents:detail", pk=pk)
