"""
Tests for the contact app — public contact form + newsletter signup.
"""
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from contact.models import ContactMessage, NewsletterSubscriber


class ContactMessageViewTests(TestCase):
    """POST /api/contact/message/"""

    def setUp(self):
        self.client = APIClient()
        self.url = reverse("contact:message")
        self.valid_payload = {
            "name": "John Doe",
            "email": "john@example.com",
            "phone_number": "08012345678",
            "subject": "Question about sizing",
            "message": "Do the vests run true to size, or should I size up?",
        }

    @patch("contact.views.send_email_async")
    def test_submits_message_without_authentication(self, mock_email):
        response = self.client.post(self.url, self.valid_payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ContactMessage.objects.count(), 1)

        message = ContactMessage.objects.first()
        self.assertEqual(message.name, "John Doe")
        self.assertEqual(message.email, "john@example.com")
        self.assertFalse(message.is_handled)

    @patch("contact.views.send_email_async")
    def test_notifies_the_team(self, mock_email):
        self.client.post(self.url, self.valid_payload, format="json")

        mock_email.assert_called_once()
        _, kwargs = mock_email.call_args
        self.assertIn("Question about sizing", kwargs["subject"])
        self.assertIn("john@example.com", kwargs["message"])

    @patch("contact.views.send_email_async")
    def test_phone_number_is_optional(self, mock_email):
        payload = {**self.valid_payload}
        payload.pop("phone_number")

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ContactMessage.objects.first().phone_number, "")

    @patch("contact.views.send_email_async")
    def test_rejects_invalid_email(self, mock_email):
        payload = {**self.valid_payload, "email": "not-an-email"}

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ContactMessage.objects.count(), 0)

    @patch("contact.views.send_email_async")
    def test_rejects_too_short_message(self, mock_email):
        payload = {**self.valid_payload, "message": "hi"}

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ContactMessage.objects.count(), 0)

    @patch("contact.views.send_email_async")
    def test_rejects_missing_required_fields(self, mock_email):
        response = self.client.post(self.url, {"email": "a@b.com"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ContactMessage.objects.count(), 0)

    @patch("contact.views.send_email_async", side_effect=Exception("SMTP down"))
    def test_notification_failure_still_returns_success(self, mock_email):
        """
        A mail outage must not lose the visitor's message, and must not tell
        them it failed — otherwise they resubmit and we get duplicates of a
        message we already have.
        """
        response = self.client.post(self.url, self.valid_payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ContactMessage.objects.count(), 1)


class NewsletterSubscribeViewTests(TestCase):
    """POST /api/contact/subscribe/"""

    def setUp(self):
        self.client = APIClient()
        self.url = reverse("contact:subscribe")

    def test_subscribes_without_authentication(self):
        response = self.client.post(
            self.url, {"email": "reader@example.com"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            NewsletterSubscriber.objects.filter(email="reader@example.com").exists()
        )

    def test_email_is_normalised_to_lowercase(self):
        response = self.client.post(
            self.url, {"email": "  Reader@Example.COM  "}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            NewsletterSubscriber.objects.filter(email="reader@example.com").exists()
        )

    def test_resubscribing_is_a_friendly_noop_not_an_error(self):
        NewsletterSubscriber.objects.create(email="reader@example.com")

        response = self.client.post(
            self.url, {"email": "reader@example.com"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("already subscribed", response.data["detail"].lower())
        self.assertEqual(NewsletterSubscriber.objects.count(), 1)

    def test_resubscribing_reactivates_an_unsubscribed_address(self):
        NewsletterSubscriber.objects.create(email="reader@example.com", is_active=False)

        response = self.client.post(
            self.url, {"email": "reader@example.com"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        subscriber = NewsletterSubscriber.objects.get(email="reader@example.com")
        self.assertTrue(subscriber.is_active)
        self.assertEqual(NewsletterSubscriber.objects.count(), 1)

    def test_rejects_invalid_email(self):
        response = self.client.post(self.url, {"email": "nope"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(NewsletterSubscriber.objects.count(), 0)

    def test_rejects_missing_email(self):
        response = self.client.post(self.url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(NewsletterSubscriber.objects.count(), 0)
