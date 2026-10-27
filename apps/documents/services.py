"""Document upload, versioning, review and access.

Visibility, enforced here and not only in the templates:

- `owner_only`   — the uploader alone.
- `department`   — anyone with a current role in the owning department.
- `committee`    — the uploader, plus committee-capable officers (committees.manage).
- `collaboration`— partner-department representatives, pending Phase 4; until then the
                   owning department and collaboration.respond holders.
- `public`       — any signed-in user, in any department.

Department scoping comes first in every case: a document belongs to one department, and no
visibility level except `public` reaches outside it. Files themselves live in a private store
and are only ever streamed by a view that has already called `can_read`.
"""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.access.services import has_any_perm, has_perm, permission_codes
from apps.audit.services import record, snapshot

from . import storage
from .models import Document

MANAGE = "committees.manage"
REVIEW = "committees.manage"
COLLABORATION = "collaboration.respond"


class DocumentError(Exception):
    """A business-rule violation with a message safe to show to the user."""


def require_perm(actor, code, department):
    """Services re-check permissions so they're safe to call from views, the API or tasks."""
    if not has_perm(actor, code, department):
        raise PermissionDenied(f"Missing permission {code}.")


def readable_documents(user, department):
    """Documents in `department` that `user` may read."""
    qs = Document.objects.filter(department=department)
    if not permission_codes(user, department):
        # No role in this department: only explicitly public documents.
        return qs.filter(visibility=Document.Visibility.PUBLIC)
    allowed = Q(visibility__in=(Document.Visibility.DEPARTMENT, Document.Visibility.PUBLIC))
    allowed |= Q(uploaded_by=user)  # you can always read your own
    if has_perm(user, MANAGE, department):
        allowed |= Q(visibility=Document.Visibility.COMMITTEE)
    if has_any_perm(user, (COLLABORATION, MANAGE), department):
        allowed |= Q(visibility=Document.Visibility.COLLABORATION)
    return qs.filter(allowed)


def can_read(user, document):
    return readable_documents(user, document.department).filter(pk=document.pk).exists()


def can_edit(user, document):
    """The uploader, or a committees.manage holder in the owning department."""
    if document.uploaded_by_id == user.pk:
        return True
    return has_perm(user, MANAGE, document.department)


def _require_editor(actor, document):
    if not can_edit(actor, document):
        raise PermissionDenied("You can't change this document.")


@transaction.atomic
def upload(
    *,
    actor,
    department,
    upload_file,
    title,
    category="other",
    visibility=Document.Visibility.DEPARTMENT,
    replaces=None,
):
    """Store a file privately and record its metadata.

    `replaces` makes this the next version of an existing document, which is kept.
    """
    require_perm(actor, MANAGE, department)
    problem = storage.validate(upload_file)
    if problem:
        raise DocumentError(problem)
    if replaces is not None:
        if replaces.department_id != department.pk:
            raise DocumentError("That document belongs to another department.")
        _require_editor(actor, replaces)

    digest = storage.checksum(upload_file)
    key = storage.save(upload_file, storage.build_key(department, upload_file.name))
    document = Document.objects.create(
        department=department,
        uploaded_by=actor,
        title=title,
        category=category,
        original_filename=upload_file.name[:255],
        storage_key=key,
        mime_type=(upload_file.content_type or "application/octet-stream").split(";")[0].strip(),
        file_size_bytes=upload_file.size,
        checksum_sha256=digest,
        visibility=visibility,
        version_number=(replaces.version_number + 1) if replaces else 1,
        previous_version=replaces,
        uploaded_at=timezone.now(),
    )
    record(
        "document.uploaded",
        document,
        actor=actor,
        department=department,
        after=snapshot(
            document, fields=["title", "category", "visibility", "version_number", "checksum_sha256"]
        ),
    )
    return document


@transaction.atomic
def set_visibility(document, *, actor, visibility):
    """Change who may read a document. Narrowing is always allowed; widening is audited."""
    _require_editor(actor, document)
    document = Document.objects.select_for_update().get(pk=document.pk)
    before = {"visibility": document.visibility}
    document.visibility = visibility
    document.save(update_fields=["visibility"])
    record(
        "document.visibility_changed",
        document,
        actor=actor,
        department=document.department,
        before=before,
        after={"visibility": visibility},
    )
    return document


@transaction.atomic
def review(document, *, actor, approve, note=""):
    """Approve or reject a document. The uploader can't review their own."""
    department = document.department
    require_perm(actor, REVIEW, department)
    document = Document.objects.select_for_update().get(pk=document.pk)
    if document.uploaded_by_id == actor.pk:
        raise DocumentError("Someone other than the uploader must review a document.")
    if document.review_status == Document.ReviewStatus.ARCHIVED:
        raise DocumentError("This document is archived.")
    before = {"review_status": document.review_status}
    document.review_status = Document.ReviewStatus.APPROVED if approve else Document.ReviewStatus.REJECTED
    document.save(update_fields=["review_status"])
    record(
        "document.approved" if approve else "document.rejected",
        document,
        actor=actor,
        department=department,
        before=before,
        after={"review_status": document.review_status, "note": note},
    )
    return document


@transaction.atomic
def submit_for_review(document, *, actor):
    _require_editor(actor, document)
    document = Document.objects.select_for_update().get(pk=document.pk)
    if document.review_status not in (
        Document.ReviewStatus.DRAFT,
        Document.ReviewStatus.REJECTED,
    ):
        raise DocumentError("Only a draft or rejected document can be sent for review.")
    document.review_status = Document.ReviewStatus.PENDING_REVIEW
    document.save(update_fields=["review_status"])
    record("document.submitted_for_review", document, actor=actor, department=document.department)
    return document


@transaction.atomic
def archive(document, *, actor):
    """Archive rather than delete: the file and its history are kept."""
    _require_editor(actor, document)
    document = Document.objects.select_for_update().get(pk=document.pk)
    before = {"review_status": document.review_status}
    document.review_status = Document.ReviewStatus.ARCHIVED
    document.save(update_fields=["review_status"])
    record(
        "document.archived",
        document,
        actor=actor,
        department=document.department,
        before=before,
        after={"review_status": document.review_status},
    )
    return document


def record_download(document, *, actor):
    """Every read of a private file leaves a trace."""
    record(
        "document.downloaded",
        document,
        actor=actor,
        department=document.department,
        after={"filename": document.original_filename},
    )


def version_history(document):
    """Every version of this document, oldest first."""
    chain, seen = [], set()
    current = document
    while current is not None and current.pk not in seen:
        chain.append(current)
        seen.add(current.pk)
        current = current.previous_version
    chain.reverse()
    nxt = document.next_versions.order_by("version_number").first()
    while nxt is not None and nxt.pk not in seen:
        chain.append(nxt)
        seen.add(nxt.pk)
        nxt = nxt.next_versions.order_by("version_number").first()
    return chain
