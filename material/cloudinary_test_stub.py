"""
Offline stand-ins for Cloudinary's upload/destroy calls, used only by the
test runner (material/test_runner.py) and pytest (conftest.py).

Without this, any test that saves a model with an image/file field really
uploads to the live Cloudinary account (the local .env uses the production
credentials) — a run of the feed tests once dumped ~330 junk images into the
production media library. The Django test database is isolated, Cloudinary
is not.
"""

import os
import uuid
from unittest import mock


def _fake_upload(file, **options):
    raw_name = getattr(file, "name", None) or (file if isinstance(file, str) else "file")
    base = os.path.basename(str(raw_name).split("?")[0])
    stem, ext = os.path.splitext(base)
    stem = stem or "file"
    ext = ext.lstrip(".").lower() or "jpg"

    public_id = options.get("public_id") or f"{stem}_{uuid.uuid4().hex[:6]}"
    folder = options.get("folder")
    if folder and not public_id.startswith(f"{folder}/"):
        public_id = f"{folder}/{public_id}"

    resource_type = options.get("resource_type") or "image"
    if resource_type == "auto":
        resource_type = "video" if ext in {"mp4", "mov", "webm", "avi"} else "image"

    url = f"https://res.cloudinary.com/test-cloud/{resource_type}/upload/v1/{public_id}.{ext}"
    return {
        "public_id": public_id,
        "version": 1,
        "signature": "test-signature",
        "format": ext,
        "type": "upload",
        "resource_type": resource_type,
        "url": url,
        "secure_url": url,
        "bytes": 1,
        "width": 1,
        "height": 1,
        "etag": "test-etag",
    }


def _fake_destroy(public_id, **options):
    return {"result": "ok"}


_patchers = []


def start():
    if _patchers:
        return
    for target, fake in (
        ("cloudinary.uploader.upload", _fake_upload),
        ("cloudinary.uploader.destroy", _fake_destroy),
    ):
        patcher = mock.patch(target, side_effect=fake)
        patcher.start()
        _patchers.append(patcher)


def stop():
    while _patchers:
        _patchers.pop().stop()
