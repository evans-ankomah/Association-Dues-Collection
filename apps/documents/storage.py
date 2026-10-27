"""Private document store.

Files live outside MEDIA_ROOT and are never reachable by URL. The only way to read one is
`apps.documents.views.download`, which checks permissions first and then streams the bytes.
"""

import hashlib
import uuid
from pathlib import PurePosixPath

from django.conf import settings
from django.core.files.storage import storages

CHUNK = 64 * 1024


def store():
    return storages["documents"]


def build_key(department, filename):
    """A storage key that can't be guessed and can't escape the store."""
    suffix = PurePosixPath(filename).suffix[:16]
    return f"{department.pk}/{uuid.uuid4()}{suffix}"


def checksum(upload):
    """SHA-256 of an uploaded file, read in chunks so a large file isn't held in memory."""
    digest = hashlib.sha256()
    for chunk in upload.chunks(CHUNK):
        digest.update(chunk)
    upload.seek(0)
    return digest.hexdigest()


def save(upload, key):
    return store().save(key, upload)


def open_file(key):
    return store().open(key, "rb")


def delete(key):
    backend = store()
    if backend.exists(key):
        backend.delete(key)


def validate(upload):
    """Size and type checks. Returns an error message, or None when the file is acceptable."""
    if upload.size > settings.DOCUMENT_MAX_BYTES:
        limit = settings.DOCUMENT_MAX_BYTES // (1024 * 1024)
        return f"That file is larger than the {limit} MB limit."
    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    if content_type not in settings.DOCUMENT_ALLOWED_TYPES:
        return "That file type isn't accepted."
    return None
