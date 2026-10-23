import os
from pathlib import Path

import environ

# Read .env before applying defaults so values in .env win.
environ.Env.read_env(Path(__file__).resolve().parent.parent.parent / ".env")
os.environ.setdefault("SECRET_KEY", "dev-insecure-key-change-me")
os.environ.setdefault("DATABASE_URL", "postgres://depthub:depthub@localhost:5433/depthub")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("ALLOWED_HOSTS", "localhost,127.0.0.1")

from .base import *  # noqa: E402,F403

STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
}
