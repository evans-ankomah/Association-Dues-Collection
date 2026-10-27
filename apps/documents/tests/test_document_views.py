import pytest

from apps.audit.models import AuditEvent
from apps.common.tests.factories import DepartmentFactory
from apps.documents.models import Document

pytestmark = pytest.mark.django_db


def test_officer_uploads_and_downloads(secretary, login, pdf, department):
    response = login(secretary).post(
        "/documents/upload/",
        {
            "title": "Executive minutes",
            "category": "minutes",
            "visibility": "department",
            "upload": pdf(content=b"%PDF-1.4 minutes body"),
        },
    )
    assert response.status_code == 302
    document = Document.objects.get(title="Executive minutes")
    assert document.department == department

    download = login(secretary).get(f"/documents/{document.pk}/download/")
    assert download.status_code == 200
    assert b"".join(download.streaming_content) == b"%PDF-1.4 minutes body"
    assert download["Cache-Control"] == "private, no-store"
    assert download["X-Content-Type-Options"] == "nosniff"


def test_downloads_are_audited(make_document, secretary, login):
    document = make_document()
    login(secretary).get(f"/documents/{document.pk}/download/")
    assert AuditEvent.objects.filter(action_key="document.downloaded", entity_id=document.pk).exists()


def test_owner_only_document_cannot_be_downloaded_by_another_officer(make_document, other_secretary, login):
    document = make_document(visibility=Document.Visibility.OWNER_ONLY)
    client = login(other_secretary)
    assert client.get(f"/documents/{document.pk}/").status_code == 403
    assert client.get(f"/documents/{document.pk}/download/").status_code == 403


def test_member_cannot_reach_documents_at_all(make_document, member, login):
    """Documents are gated on committees.manage, which a plain member doesn't hold."""
    document = make_document(visibility=Document.Visibility.DEPARTMENT)
    client = login(member)
    assert client.get("/documents/").status_code == 403
    assert client.get(f"/documents/{document.pk}/").status_code == 403
    assert client.get(f"/documents/{document.pk}/download/").status_code == 403
    assert client.get("/documents/upload/").status_code == 403


def test_officer_cannot_reach_another_departments_document(secretary, login, department):
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
    client = login(secretary)
    assert client.get(f"/documents/{foreign.pk}/").status_code == 404
    assert client.get(f"/documents/{foreign.pk}/download/").status_code == 404
    assert client.post(f"/documents/{foreign.pk}/action/", {"action": "archive"}).status_code == 404


def test_committee_documents_are_absent_from_a_members_list(make_document, other_secretary, login):
    make_document(visibility=Document.Visibility.COMMITTEE, title="Committee paper")
    make_document(visibility=Document.Visibility.DEPARTMENT, title="Department policy")
    body = login(other_secretary).get("/documents/").content.decode()
    assert "Committee paper" in body  # holds committees.manage
    assert "Department policy" in body


def test_uploader_cannot_approve_their_own_document(make_document, secretary, login):
    document = make_document()
    login(secretary).post(f"/documents/{document.pk}/action/", {"action": "submit"})
    response = login(secretary).post(f"/documents/{document.pk}/action/", {"action": "approve"})
    document.refresh_from_db()
    assert response.status_code == 302
    assert document.review_status == Document.ReviewStatus.PENDING_REVIEW


def test_rejected_file_type_over_http_stores_nothing(secretary, login):
    from django.core.files.uploadedfile import SimpleUploadedFile

    login(secretary).post(
        "/documents/upload/",
        {
            "title": "Bad",
            "category": "other",
            "visibility": "department",
            "upload": SimpleUploadedFile("x.exe", b"MZ", content_type="application/x-msdownload"),
        },
    )
    assert not Document.objects.exists()


def test_anonymous_is_redirected_to_sign_in(make_document, client):
    document = make_document()
    assert client.get("/documents/").status_code == 302
    assert client.get(f"/documents/{document.pk}/download/").status_code == 302
