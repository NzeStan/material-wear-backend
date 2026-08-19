from django.db import models
import uuid


class ContactMessage(models.Model):
    """A message submitted through the public Contact page form."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    email = models.EmailField()
    phone_number = models.CharField(max_length=20, blank=True)
    subject = models.CharField(max_length=150)
    message = models.TextField()

    is_handled = models.BooleanField(
        default=False,
        help_text="Mark once someone has responded to this message",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Contact Message"
        verbose_name_plural = "Contact Messages"
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["is_handled"]),
        ]

    def __str__(self):
        return f"{self.name} <{self.email}> — {self.subject}"


class NewsletterSubscriber(models.Model):
    """An email address subscribed via the footer newsletter form."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(
        default=True,
        help_text="Uncheck instead of deleting, so a resubscribe keeps history",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Newsletter Subscriber"
        verbose_name_plural = "Newsletter Subscribers"

    def __str__(self):
        return f"{self.email} ({'active' if self.is_active else 'unsubscribed'})"
