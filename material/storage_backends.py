"""
Custom storage backends.

cloudinary_storage does not seek the file back to position 0 before
uploading.  Django's request parser may advance the file pointer during
validation/content-type detection, leaving it at EOF.  Cloudinary then
receives empty bytes and responds with "Invalid image file".

This wrapper seeks to 0 before every upload, making it safe regardless of
how far the pointer has been advanced beforehand.
"""

from cloudinary_storage.storage import MediaCloudinaryStorage


class SeekableMediaCloudinaryStorage(MediaCloudinaryStorage):
    """MediaCloudinaryStorage that rewinds the file before uploading."""

    def _save(self, name, content):
        if hasattr(content, "seek"):
            content.seek(0)
        return super()._save(name, content)
