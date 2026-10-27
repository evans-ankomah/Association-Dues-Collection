import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.documents import services as svc


@pytest.fixture(autouse=True)
def private_document_root(tmp_path, settings):
    """Keep every test's uploads in a throwaway directory, never the real document store."""
    settings.STORAGES = {
        **settings.STORAGES,
        "documents": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(tmp_path / "documents")},
        },
    }
    yield tmp_path


@pytest.fixture
def secretary(make_user, session):
    """Holds committees.manage, which governs documents."""
    return make_user("department_secretary", session=session)


@pytest.fixture
def other_secretary(make_user, session):
    return make_user("department_president", session=session)


@pytest.fixture
def pdf():
    def _make(name="minutes.pdf", content=b"%PDF-1.4 fake pdf body"):
        return SimpleUploadedFile(name, content, content_type="application/pdf")

    return _make


@pytest.fixture
def make_document(department, secretary, pdf):
    def _make(actor=None, **kwargs):
        kwargs.setdefault("title", "Executive minutes")
        kwargs.setdefault("category", "minutes")
        return svc.upload(
            actor=actor or secretary,
            department=kwargs.pop("department", department),
            upload_file=kwargs.pop("upload_file", pdf()),
            **kwargs,
        )

    return _make
