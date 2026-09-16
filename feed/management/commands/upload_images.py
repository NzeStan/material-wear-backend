# feed/management/commands/upload_images.py
"""
Management command to upload images to feed, from either a CSV of URLs or
a local folder of image files.

CSV Format:
-----------
image_url,active
https://example.com/image1.jpg,true
https://example.com/image2.jpg,false
https://res.cloudinary.com/demo/image/upload/feed_images/banner.jpg,true

Supported URLs:
--------------
✅ External URLs (http/https): Downloaded and uploaded to Cloudinary
✅ Cloudinary URLs: Reused by public_id (NO duplication!)

Local folder mode:
-------------------
Every .jpg/.jpeg/.png/.webp/.gif file directly inside the given folder
(not recursive) is uploaded to Cloudinary and saved as active=True. Re-running
against the same folder creates new rows each time — same as the CSV path,
which doesn't dedupe either — so don't re-run on a folder you've already
uploaded unless you want duplicates.

NOTE: --folder is a path on whatever machine RUNS this command. If you run
it in a shell on the deployed server (Render, etc.), it can only see that
server's own filesystem — not your computer. Either run this command
locally (pointed at production settings), or use --cloudinary-folder below.

Cloudinary-folder sync mode:
-----------------------------
For bulk-uploading straight from your computer: upload the images yourself
via Cloudinary's own Media Library (cloudinary.com console, drag-and-drop
into a folder, e.g. "feed_images") — no server involved — then run this
command with --cloudinary-folder to scan that Cloudinary folder via the
Admin API and create any feed.Image rows that don't exist yet. This IS
deduped: re-running only picks up images added since the last sync.

Usage:
------
python manage.py upload_images path/to/images.csv
python manage.py upload_images path/to/images.csv --dry-run
python manage.py upload_images --folder path/to/local/images
python manage.py upload_images --folder path/to/local/images --dry-run
python manage.py upload_images --cloudinary-folder feed_images
python manage.py upload_images --cloudinary-folder feed_images --dry-run
"""

import csv
import requests
import logging
import re
from pathlib import Path
import cloudinary.api
from django.core.management.base import BaseCommand, CommandError
from django.core.files import File
from django.core.files.temp import NamedTemporaryFile
from django.db import transaction
from feed.models import Image

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class Command(BaseCommand):
    help = "Upload images to the feed app, from a CSV of URLs, a local folder, or a Cloudinary folder sync"

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_file", type=str, nargs="?", default=None, help="Path to CSV file"
        )
        parser.add_argument(
            "--folder",
            type=str,
            default=None,
            help="Path to a local folder of images to upload directly to Cloudinary "
            "(local to whatever machine runs this command)",
        )
        parser.add_argument(
            "--cloudinary-folder",
            type=str,
            default=None,
            help="Cloudinary folder prefix (e.g. 'feed_images') to sync from — "
            "creates feed.Image rows for anything in that folder not already imported",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without saving to database",
        )

    def handle(self, *args, **options):
        csv_file = options["csv_file"]
        folder = options["folder"]
        cloudinary_folder = options["cloudinary_folder"]
        dry_run = options["dry_run"]

        modes = [bool(csv_file), bool(folder), bool(cloudinary_folder)]
        if sum(modes) != 1:
            raise CommandError(
                "Provide exactly one of: a CSV file path, --folder <path>, "
                "or --cloudinary-folder <prefix>"
            )

        # Header
        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write(self.style.SUCCESS("  MATERIAL ACCESSORIES - IMAGE UPLOAD"))
        self.stdout.write(self.style.SUCCESS("=" * 80))
        source_desc = (
            csv_file
            or (f"{folder} (local folder)" if folder else None)
            or f"{cloudinary_folder} (Cloudinary folder sync)"
        )
        self.stdout.write(f"Source: {self.style.WARNING(source_desc)}")
        if dry_run:
            self.stdout.write(
                self.style.NOTICE("MODE: DRY RUN (No changes will be saved)\n")
            )

        if folder:
            self._handle_folder(folder, dry_run)
            return

        if cloudinary_folder:
            self._handle_cloudinary_folder(cloudinary_folder, dry_run)
            return

        try:
            # Read CSV
            with open(csv_file, "r", encoding="utf-8") as file:
                reader = csv.DictReader(file)
                rows = list(reader)

            if not rows:
                raise CommandError("CSV file is empty")

            self.stdout.write(f"Found {len(rows)} images to process\n")

            # Validate headers
            self._validate_headers(reader.fieldnames)

            # Process images
            success_count = error_count = 0
            errors = []

            for idx, row in enumerate(rows, start=1):
                image_url = row.get("image_url", "").strip()
                self.stdout.write(f"\n[{idx}/{len(rows)}] {image_url[:60]}...")

                try:
                    with transaction.atomic():
                        result = self._process_image(row, dry_run)

                        if result == "success":
                            success_count += 1
                            self.stdout.write(self.style.SUCCESS("  ✓ Uploaded"))

                except Exception as e:
                    error_count += 1
                    error_msg = f"Row {idx}: {str(e)}"
                    errors.append(error_msg)
                    self.stdout.write(self.style.ERROR(f"  ✗ Error: {str(e)}"))

            # Summary
            self.stdout.write("\n" + "=" * 80)
            self.stdout.write(self.style.SUCCESS("UPLOAD SUMMARY"))
            self.stdout.write("=" * 80)
            self.stdout.write(f"Total Processed: {len(rows)}")
            self.stdout.write(self.style.SUCCESS(f"✓ Successful: {success_count}"))
            if error_count:
                self.stdout.write(self.style.ERROR(f"✗ Errors: {error_count}"))
                self.stdout.write("\nError Details:")
                for err in errors:
                    self.stdout.write(self.style.ERROR(f"  • {err}"))

            self.stdout.write("=" * 80 + "\n")

            if dry_run:
                self.stdout.write(
                    self.style.NOTICE(
                        "DRY RUN COMPLETE - No changes were saved to the database"
                    )
                )
            elif error_count == 0:
                self.stdout.write(
                    self.style.SUCCESS("✓ Upload completed successfully!")
                )
            else:
                self.stdout.write(
                    self.style.WARNING("⚠ Upload completed with some errors")
                )

        except FileNotFoundError:
            raise CommandError(f"CSV file not found: {csv_file}")
        except UnicodeDecodeError:
            raise CommandError("CSV file encoding error. Ensure file is UTF-8 encoded")
        except Exception as e:
            raise CommandError(f"Unexpected error: {str(e)}")

    def _handle_folder(self, folder, dry_run):
        """Upload every image file directly inside `folder` (not recursive)."""
        folder_path = Path(folder)
        if not folder_path.is_dir():
            raise CommandError(f"Folder not found: {folder}")

        files = sorted(
            p
            for p in folder_path.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
        )

        if not files:
            raise CommandError(
                f"No image files ({', '.join(sorted(IMAGE_EXTENSIONS))}) found in: {folder}"
            )

        self.stdout.write(f"Found {len(files)} images to process\n")

        success_count = error_count = 0
        errors = []

        for idx, path in enumerate(files, start=1):
            self.stdout.write(f"\n[{idx}/{len(files)}] {path.name}")
            try:
                with transaction.atomic():
                    self._create_image_from_local_file(path, dry_run)
                success_count += 1
                self.stdout.write(
                    self.style.SUCCESS("  (would upload)" if dry_run else "  ✓ Uploaded")
                )
            except Exception as e:
                error_count += 1
                errors.append(f"{path.name}: {str(e)}")
                self.stdout.write(self.style.ERROR(f"  ✗ Error: {str(e)}"))

        self._print_summary(len(files), success_count, error_count, errors, dry_run)

    def _handle_cloudinary_folder(self, folder_prefix, dry_run):
        """
        Scan a Cloudinary folder via the Admin API and create a feed.Image
        row for every resource in it that isn't already imported (matched by
        the same "public_id.format" string _extract_cloudinary_public_id
        produces elsewhere in this file, so dedup checks work either way an
        image got imported).
        """
        resources = []
        next_cursor = None
        while True:
            kwargs = {"type": "upload", "prefix": folder_prefix, "max_results": 500}
            if next_cursor:
                kwargs["next_cursor"] = next_cursor
            try:
                page = cloudinary.api.resources(**kwargs)
            except Exception as e:
                raise CommandError(f"Cloudinary API error: {str(e)}")
            resources.extend(page.get("resources", []))
            next_cursor = page.get("next_cursor")
            if not next_cursor:
                break

        if not resources:
            raise CommandError(f"No images found in Cloudinary folder: {folder_prefix}")

        self.stdout.write(f"Found {len(resources)} images in Cloudinary folder\n")

        success_count = skip_count = error_count = 0
        errors = []

        for idx, resource in enumerate(resources, start=1):
            public_id = f"{resource['public_id']}.{resource['format']}"
            self.stdout.write(f"\n[{idx}/{len(resources)}] {public_id}")
            try:
                if Image.objects.filter(url=public_id).exists():
                    skip_count += 1
                    self.stdout.write(self.style.NOTICE("  ⊘ Already imported"))
                    continue

                if dry_run:
                    self.stdout.write(self.style.SUCCESS("  (would import)"))
                else:
                    Image.objects.create(active=True, url=public_id)
                    self.stdout.write(self.style.SUCCESS("  ✓ Imported"))
                success_count += 1
            except Exception as e:
                error_count += 1
                errors.append(f"{public_id}: {str(e)}")
                self.stdout.write(self.style.ERROR(f"  ✗ Error: {str(e)}"))

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS("SYNC SUMMARY"))
        self.stdout.write("=" * 80)
        self.stdout.write(f"Total in folder: {len(resources)}")
        self.stdout.write(self.style.SUCCESS(f"✓ Imported: {success_count}"))
        if skip_count:
            self.stdout.write(self.style.NOTICE(f"⊘ Already imported: {skip_count}"))
        if error_count:
            self.stdout.write(self.style.ERROR(f"✗ Errors: {error_count}"))
            for err in errors:
                self.stdout.write(self.style.ERROR(f"  • {err}"))
        self.stdout.write("=" * 80 + "\n")

        if dry_run:
            self.stdout.write(
                self.style.NOTICE("DRY RUN COMPLETE - No changes were saved to the database")
            )

    def _create_image_from_local_file(self, path, dry_run):
        """Upload a single local file to Cloudinary as an active feed Image."""
        size = path.stat().st_size
        if size > MAX_IMAGE_BYTES:
            raise ValueError(f"Image too large (>{MAX_IMAGE_BYTES // (1024 * 1024)}MB)")

        if dry_run:
            self.stdout.write(f"    Would upload: {path.name} (active=True)")
            return

        with open(path, "rb") as fh:
            image = Image(active=True)
            image.url = File(fh, name=path.name)
            image.save()

    def _print_summary(self, total, success_count, error_count, errors, dry_run):
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS("UPLOAD SUMMARY"))
        self.stdout.write("=" * 80)
        self.stdout.write(f"Total Processed: {total}")
        self.stdout.write(self.style.SUCCESS(f"✓ Successful: {success_count}"))
        if error_count:
            self.stdout.write(self.style.ERROR(f"✗ Errors: {error_count}"))
            self.stdout.write("\nError Details:")
            for err in errors:
                self.stdout.write(self.style.ERROR(f"  • {err}"))
        self.stdout.write("=" * 80 + "\n")

        if dry_run:
            self.stdout.write(
                self.style.NOTICE(
                    "DRY RUN COMPLETE - No changes were saved to the database"
                )
            )
        elif error_count == 0:
            self.stdout.write(self.style.SUCCESS("✓ Upload completed successfully!"))
        else:
            self.stdout.write(self.style.WARNING("⚠ Upload completed with some errors"))

    def _validate_headers(self, headers):
        """Validate CSV headers"""
        required_headers = {"image_url"}
        optional_headers = {"active"}

        if not headers:
            raise CommandError("CSV file has no headers")

        header_set = set(headers)
        missing = required_headers - header_set

        if missing:
            raise CommandError(f"Missing required columns: {', '.join(missing)}")

        self.stdout.write(self.style.SUCCESS("✓ CSV headers validated"))

    def _process_image(self, row, dry_run):
        """Process a single image row"""
        image_url = row["image_url"].strip()

        if not image_url:
            raise ValueError("image_url cannot be empty")

        # Get active status (default to True)
        active = self._str_to_bool(row.get("active", "True"))

        if dry_run:
            self.stdout.write(f"    Would upload: {image_url} (active={active})")
            return "success"

        # Download/get image (returns File object OR string public_id)
        image_file = self._download_image(image_url)
        if not image_file:
            raise ValueError(f"Failed to download image from: {image_url}")

        # Create new image
        image = Image(active=active)

        # Cloudinary's ImageField accepts both:
        # - String (public_id) → references existing Cloudinary image (no duplicate!)
        # - File object → uploads new image to Cloudinary
        image.url = image_file

        image.save()

        return "success"

    def _download_image(self, url):
        """
        Download image from URL and return File object, or return Cloudinary public_id if it's a Cloudinary URL

        Returns:
            - String (public_id) for Cloudinary URLs (reuses existing image)
            - File object for regular URLs (will be uploaded to Cloudinary)
            - None if download fails
        """
        if not url or not url.strip():
            return None

        url = url.strip()

        # Check if it's a Cloudinary URL - if so, just return the public_id as a string
        if self._is_cloudinary_url(url):
            public_id = self._extract_cloudinary_public_id(url)
            if public_id:
                self.stdout.write(
                    self.style.NOTICE(
                        f"    ↻ Using existing Cloudinary image: {public_id}"
                    )
                )
                return public_id  # Return as string, not File object
            else:
                self.stdout.write(
                    self.style.WARNING(
                        "    ⚠ Invalid Cloudinary URL format, downloading instead"
                    )
                )
                # Fall through to normal download

        # Validate URL length
        if len(url) > 500:
            self.stdout.write(
                self.style.WARNING(
                    f"    ⚠ URL too long (>{500} chars), skipping download"
                )
            )
            return None

        try:
            self.stdout.write(f"    → Downloading from: {url[:60]}...")

            # Download with timeout
            response = requests.get(url, timeout=30, stream=True)
            response.raise_for_status()

            # Validate content type
            content_type = response.headers.get("content-type", "").lower()
            if "image" not in content_type:
                self.stdout.write(
                    self.style.WARNING(
                        f"    ⚠ Not an image (content-type: {content_type})"
                    )
                )
                return None

            # Validate file size (max 10MB)
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > 10 * 1024 * 1024:
                self.stdout.write(self.style.WARNING("    ⚠ Image too large (>10MB)"))
                return None

            # Extract filename from URL
            filename = url.split("/")[-1].split("?")[0]
            if not filename or "." not in filename:
                filename = "image.jpg"

            # Create temporary file.
            # django.core.files.temp.NamedTemporaryFile on Windows is a custom
            # class that always deletes on close and doesn't accept `delete`
            # (or `buffering`/`encoding`/`newline`) at all — passing it raises
            # TypeError there. POSIX's tempfile.NamedTemporaryFile defaults to
            # delete=True anyway, so omitting it is a no-op there too.
            img_temp = NamedTemporaryFile()

            # Download in chunks
            for chunk in response.iter_content(chunk_size=8192):
                img_temp.write(chunk)

            img_temp.flush()
            img_temp.seek(0)

            self.stdout.write(self.style.SUCCESS(f"    ✓ Downloaded successfully"))

            return File(img_temp, name=filename)

        except requests.Timeout:
            self.stdout.write(self.style.WARNING("    ⚠ Download timeout"))
            return None
        except requests.RequestException as e:
            self.stdout.write(self.style.WARNING(f"    ⚠ Download failed: {str(e)}"))
            return None
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"    ⚠ Unexpected error: {str(e)}"))
            return None

    def _is_cloudinary_url(self, url):
        """Check if URL is a Cloudinary URL"""
        if not url:
            return False
        return "cloudinary.com" in url.lower() and "/image/upload/" in url

    def _extract_cloudinary_public_id(self, url):
        """
        Extract public_id from Cloudinary URL

        Cloudinary URL formats:
        - https://res.cloudinary.com/{cloud_name}/image/upload/v{version}/{public_id}.{format}
        - https://res.cloudinary.com/{cloud_name}/image/upload/{transformations}/v{version}/{public_id}.{format}
        - https://res.cloudinary.com/{cloud_name}/image/upload/{public_id}.{format}

        Returns: public_id with extension (e.g., "feed_images/banner.jpg")
        """
        try:
            # Split by /image/upload/
            parts = url.split("/image/upload/")
            if len(parts) != 2:
                return None

            # Get everything after /image/upload/
            after_upload = parts[1]

            # Remove query parameters
            after_upload = after_upload.split("?")[0]

            # Split by / to get segments
            segments = after_upload.split("/")

            # Remove version (starts with 'v' followed by numbers)
            segments = [s for s in segments if not re.match(r"^v\d+$", s)]

            # Remove transformations (contains underscore, comma, or common transform prefixes)
            transform_patterns = [r"w_", r"h_", r"c_", r"q_", r"f_", r"dpr_", r"ar_"]
            segments = [
                s
                for s in segments
                if not any(pattern in s for pattern in transform_patterns)
            ]

            # What's left should be the public_id path (could be folder/filename.ext)
            public_id = "/".join(segments)

            return public_id

        except Exception as e:
            logger.error(f"Error extracting Cloudinary public_id: {str(e)}")
            return None

    def _str_to_bool(self, value):
        """
        Convert string to boolean

        True values: 'true', '1', 'yes', 'y', True
        False values: 'false', '0', 'no', 'n', False
        Empty/None: defaults to True
        """
        if value is None or (isinstance(value, str) and not value.strip()):
            return True

        if isinstance(value, bool):
            return value

        value_str = str(value).strip().lower()

        if value_str in ("true", "1", "yes", "y"):
            return True
        elif value_str in ("false", "0", "no", "n"):
            return False
        else:
            # Default to False for invalid values
            return False
