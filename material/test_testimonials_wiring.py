"""
End-to-end wiring checks for the django-testimonials integration:
submit -> moderation -> public visibility, plus the project-level fixes
(moderator-only stats, video-capable file storage).
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from material.storage_backends import SeekableMediaCloudinaryStorage

User = get_user_model()

BASE = "/api/testimonials"
NO_SIDE_EFFECTS = dict(
    TESTIMONIALS_USE_BACKGROUND_TASKS=False,
    TESTIMONIALS_SEND_EMAIL_NOTIFICATIONS=False,
    TESTIMONIALS_SEND_ADMIN_NOTIFICATIONS=False,
)


def results(response):
    data = response.data
    return data["results"] if isinstance(data, dict) and "results" in data else data


@override_settings(**NO_SIDE_EFFECTS)
class TestimonialLifecycleTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user(
            username="mod@example.com", email="mod@example.com", password="pw12345!", is_staff=True
        )
        self.payload = {
            "author_name": "Ada Obi",
            "author_email": "ada@example.com",
            "content": "Great quality corper kit, arrived on time.",
            "rating": 5,
            "source": "website",
            "is_anonymous": "false",
        }

    def _submit_as_guest(self):
        response = self.client.post(f"{BASE}/testimonials/", self.payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response.data["id"]

    def test_guest_submission_is_pending_and_hidden_from_public(self):
        self._submit_as_guest()
        cache.clear()
        listing = self.client.get(f"{BASE}/testimonials/")
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(results(listing), [])
        self.assertEqual(self.client.get(f"{BASE}/testimonials/featured/").data, [])

    def test_approve_then_feature_makes_it_public(self):
        tid = self._submit_as_guest()

        self.client.force_authenticate(user=self.staff)
        self.assertEqual(
            self.client.post(f"{BASE}/testimonials/{tid}/approve/", {}).status_code,
            status.HTTP_200_OK,
        )
        self.client.force_authenticate(user=None)
        cache.clear()
        public = results(self.client.get(f"{BASE}/testimonials/"))
        self.assertEqual([t["id"] for t in public], [tid])

        self.client.force_authenticate(user=self.staff)
        self.assertEqual(
            self.client.post(f"{BASE}/testimonials/{tid}/feature/", {}).status_code,
            status.HTTP_200_OK,
        )
        self.client.force_authenticate(user=None)
        cache.clear()
        featured = self.client.get(f"{BASE}/testimonials/featured/").data
        self.assertEqual([t["id"] for t in featured], [tid])

    def test_reject_keeps_it_hidden(self):
        tid = self._submit_as_guest()
        self.client.force_authenticate(user=self.staff)
        self.client.post(f"{BASE}/testimonials/{tid}/reject/", {"reason": "spam"})
        self.client.force_authenticate(user=None)
        cache.clear()
        self.assertEqual(results(self.client.get(f"{BASE}/testimonials/")), [])

    def test_guest_cannot_moderate(self):
        tid = self._submit_as_guest()
        for action in ("approve", "feature", "reject"):
            response = self.client.post(f"{BASE}/testimonials/{tid}/{action}/", {})
            self.assertIn(
                response.status_code,
                (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
                action,
            )

    def test_guest_cannot_attach_media(self):
        tid = self._submit_as_guest()
        upload = ContentFile(b"\x89PNG\r\n", name="proof.png")
        response = self.client.post(
            f"{BASE}/media/", {"testimonial": tid, "file": upload}, format="multipart"
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_400_BAD_REQUEST, status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )


@override_settings(**NO_SIDE_EFFECTS)
class TestimonialStatsPermissionTests(APITestCase):
    """Moderation counts (pending/rejected) must not be public."""

    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user(
            username="s@example.com", email="s@example.com", password="pw12345!", is_staff=True
        )
        self.customer = User.objects.create_user(
            username="c@example.com", email="c@example.com", password="pw12345!"
        )

    def test_anonymous_is_refused(self):
        response = self.client.get(f"{BASE}/testimonials/stats/")
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_regular_customer_is_refused(self):
        self.client.force_authenticate(user=self.customer)
        self.assertEqual(
            self.client.get(f"{BASE}/testimonials/stats/").status_code, status.HTTP_403_FORBIDDEN
        )

    def test_staff_gets_stats(self):
        self.client.force_authenticate(user=self.staff)
        response = self.client.get(f"{BASE}/testimonials/stats/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("status_distribution", response.data)


class SeekableStorageResourceTypeTests(TestCase):
    """Videos/docs must not be uploaded to Cloudinary as 'image'."""

    def setUp(self):
        self.storage = SeekableMediaCloudinaryStorage()

    def _upload_options(self, filename):
        with mock.patch("cloudinary.uploader.upload", wraps=__import__(
            "material.cloudinary_test_stub", fromlist=["_fake_upload"]
        )._fake_upload) as upload:
            name = self.storage.save(f"testimonials/{filename}", ContentFile(b"data", name=filename))
        return name, upload.call_args.kwargs

    def test_video_upload_uses_video_resource_type_and_keeps_extension(self):
        name, options = self._upload_options("clip.mp4")
        self.assertEqual(options["resource_type"], "video")
        self.assertTrue(name.endswith(".mp4"), name)
        self.assertIn("/video/upload/", self.storage.url(name))

    def test_image_upload_is_unchanged(self):
        name, options = self._upload_options("photo.jpg")
        self.assertEqual(options["resource_type"], "image")
        self.assertFalse(name.endswith(".jpg"), name)
        self.assertIn("/image/upload/", self.storage.url(name))

    def test_document_upload_uses_raw_resource_type(self):
        _, options = self._upload_options("notes.docx")
        self.assertEqual(options["resource_type"], "raw")

    def test_deleting_a_video_strips_the_extension_from_the_public_id(self):
        with mock.patch("cloudinary.uploader.destroy", return_value={"result": "ok"}) as destroy:
            self.assertTrue(self.storage.delete("media/testimonials/clip_ab12cd.mp4"))
        destroy.assert_called_once_with(
            "media/testimonials/clip_ab12cd", invalidate=True, resource_type="video"
        )
