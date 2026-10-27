import hashlib

import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.common.tests.factories import DepartmentFactory
from apps.documents import services as svc
from apps.documents import storage
from apps.documents.models import Document
from apps.documents.services import DocumentError

pytestmark = pytest.mark.django_db


def test_upload_records_metadata_and_checksum(department, secretary, pdf):
    body = b"%PDF-1.4 the real bytes"
    document = svc.upload(
        actor=secretary,
        department=department,
        upload_file=pdf(content=body),
        title="Executive minutes",
        category="minutes",
    )
    assert document.department == department
    assert document.uploaded_by == secretary
    assert document.file_size_bytes == len(body)
    assert document.checksum_sha256 == hashlib.sha256(body).hexdigest()
    assert document.version_number == 1
    # The key is opaque and scoped to the department, never the original name.
    assert document.original_filename not in document.storage_key
    assert str(department.pk) in document.storage_key
    with storage.open_file(document.storage_key) as handle:
        assert handle.read() == body


def test_oversized_files_are_refused(department, secretary, settings):
    settings.DOCUMENT_MAX_BYTES = 10
    big = SimpleUploadedFile("big.pdf", b"x" * 50, content_type="application/pdf")
    with pytest.raises(DocumentError, match="larger than"):
        svc.upload(actor=secretary, department=department, upload_file=big, title="Big")
    assert not Document.objects.exists()


def test_unaccepted_file_types_are_refused(department, secretary):
    script = SimpleUploadedFile("run.exe", b"MZ", content_type="application/x-msdownload")
    with pytest.raises(DocumentError, match="file type isn't accepted"):
        svc.upload(actor=secretary, department=department, upload_file=script, title="Nope")
    assert not Document.objects.exists()


def test_new_version_keeps_the_old_one(make_document, secretary, pdf, department):
    first = make_document(title="Constitution")
    second = svc.upload(
        actor=secretary,
        department=department,
        upload_file=pdf(content=b"%PDF-1.4 v2"),
        title="Constitution",
        replaces=first,
    )
    assert second.version_number == 2
    assert second.previous_version == first
    assert Document.objects.count() == 2
    assert svc.version_history(second) == [first, second]
    # The list view shows only the newest version by default.
    current = list(Document.objects.current())
    assert second in current
    assert first not in current


def test_reviewer_must_not_be_the_uploader(make_document, secretary):
    document = make_document()
    svc.submit_for_review(document, actor=secretary)
    with pytest.raises(DocumentError, match="other than the uploader"):
        svc.review(document, actor=secretary, approve=True)


def test_another_officer_can_review(make_document, secretary, other_secretary):
    document = make_document()
    svc.submit_for_review(document, actor=secretary)
    svc.review(document, actor=other_secretary, approve=True)
    document.refresh_from_db()
    assert document.review_status == Document.ReviewStatus.APPROVED


def test_archiving_keeps_the_record(make_document, secretary):
    document = make_document()
    svc.archive(document, actor=secretary)
    document.refresh_from_db()
    assert document.review_status == Document.ReviewStatus.ARCHIVED
    assert Document.objects.filter(pk=document.pk).exists()


# --- visibility -------------------------------------------------------------------------------


def test_owner_only_documents_are_private_to_the_uploader(make_document, secretary, other_secretary):
    document = make_document(visibility=Document.Visibility.OWNER_ONLY)
    assert svc.can_read(secretary, document)
    assert not svc.can_read(other_secretary, document)


def test_department_documents_are_readable_by_members(make_document, member):
    document = make_document(visibility=Document.Visibility.DEPARTMENT)
    assert svc.can_read(member, document)


def test_committee_documents_are_hidden_from_plain_members(make_document, member, other_secretary):
    document = make_document(visibility=Document.Visibility.COMMITTEE)
    assert not svc.can_read(member, document)
    assert svc.can_read(other_secretary, document)  # holds committees.manage


def test_a_user_with_no_role_in_the_department_sees_only_public(make_document, make_user, department):
    outsider = make_user()  # no role granted
    departmental = make_document(visibility=Document.Visibility.DEPARTMENT)
    public = make_document(visibility=Document.Visibility.PUBLIC, title="Open policy")
    assert not svc.can_read(outsider, departmental)
    assert svc.can_read(outsider, public)


def test_documents_do_not_leak_across_departments(make_document, secretary, department, pdf):
    other_dept = DepartmentFactory(institution=department.institution)
    foreign = Document.objects.create(
        department=other_dept,
        uploaded_by=secretary,
        title="Their minutes",
        category="minutes",
        original_filename="x.pdf",
        storage_key="k",
        mime_type="application/pdf",
        file_size_bytes=1,
        checksum_sha256="0" * 64,
        visibility=Document.Visibility.PUBLIC,
    )
    # Even a PUBLIC document in another department is outside this department's list.
    assert foreign not in svc.readable_documents(secretary, department)
    # And the uploader can't review it there, because they hold no role in that department.
    with pytest.raises(PermissionDenied):
        svc.review(foreign, actor=secretary, approve=True)


def test_uploading_into_another_department_is_refused(secretary, department, pdf):
    other_dept = DepartmentFactory(institution=department.institution)
    with pytest.raises(PermissionDenied):
        svc.upload(actor=secretary, department=other_dept, upload_file=pdf(), title="Sneaky")


def test_a_member_cannot_upload(member, department, pdf):
    """Uploading needs committees.manage; reading a department document does not."""
    with pytest.raises(PermissionDenied):
        svc.upload(actor=member, department=department, upload_file=pdf(), title="Nope")


def test_a_member_cannot_change_visibility_or_archive(make_document, member):
    document = make_document(visibility=Document.Visibility.DEPARTMENT)
    with pytest.raises(PermissionDenied):
        svc.set_visibility(document, actor=member, visibility=Document.Visibility.PUBLIC)
    with pytest.raises(PermissionDenied):
        svc.archive(document, actor=member)


def test_replacing_a_foreign_document_is_refused(make_document, secretary, department, pdf):
    other_dept = DepartmentFactory(institution=department.institution)
    foreign = Document.objects.create(
        department=other_dept,
        uploaded_by=secretary,
        title="Theirs",
        category="other",
        original_filename="x.pdf",
        storage_key="k",
        mime_type="application/pdf",
        file_size_bytes=1,
        checksum_sha256="0" * 64,
    )
    with pytest.raises(DocumentError, match="another department"):
        svc.upload(
            actor=secretary,
            department=department,
            upload_file=pdf(),
            title="v2",
            replaces=foreign,
        )
