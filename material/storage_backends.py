"""
Custom storage backends.

cloudinary_storage does not seek the file back to position 0 before
uploading.  Django's request parser may advance the file pointer during
validation/content-type detection, leaving it at EOF.  Cloudinary then
receives empty bytes and responds with "Invalid image file".

This wrapper seeks to 0 before every upload, making it safe regardless of
how far the pointer has been advanced beforehand.

It also picks Cloudinary's resource type from the file extension. The stock
MediaCloudinaryStorage always uploads as "image", so a video (or audio /
document) saved through the default storage — e.g. the video attachments on
testimonials — is rejected by Cloudinary as an invalid image.
"""

import os

import cloudinary.uploader
from cloudinary_storage.storage import MediaCloudinaryStorage
from django.core.files.uploadedfile import UploadedFile

# Cloudinary stores audio under the "video" resource type.
VIDEO_EXTENSIONS = {"mp4", "webm", "mov", "avi", "mkv", "m4v", "mp3", "wav", "ogg", "aac", "flac", "m4a"}
RAW_EXTENSIONS = {"doc", "docx", "txt", "rtf", "csv", "xls", "xlsx", "ppt", "pptx", "zip"}


def _extension(name):
    return os.path.splitext(name)[1].lstrip(".").lower()


class SeekableMediaCloudinaryStorage(MediaCloudinaryStorage):
    """MediaCloudinaryStorage that rewinds the file and uses the right resource type."""

    def _get_resource_type(self, name):
        ext = _extension(name)
        if ext in VIDEO_EXTENSIONS:
            return "video"
        if ext in RAW_EXTENSIONS:
            return "raw"
        return super()._get_resource_type(name)

    def _save(self, name, content):
        if hasattr(content, "seek"):
            content.seek(0)

        name = self._prepend_prefix(self._normalise_name(name))
        content = UploadedFile(content, name)
        response = self._upload(name, content)
        public_id = response["public_id"]

        # Cloudinary's video public_ids carry no extension, but the extension
        # is how _get_resource_type() recognises a video again when the URL is
        # built later — keep it in the stored name. (Raw public_ids already
        # include theirs; images keep the existing extension-less behaviour.)
        if response.get("resource_type") == "video" and response.get("format"):
            public_id = f"{public_id}.{response['format']}"
        return public_id

    def delete(self, name):
        resource_type = self._get_resource_type(name)
        public_id = os.path.splitext(name)[0] if resource_type == "video" else name
        response = cloudinary.uploader.destroy(
            public_id, invalidate=True, resource_type=resource_type
        )
        return response["result"] == "ok"
