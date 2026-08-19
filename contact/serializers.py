from rest_framework import serializers

from .models import ContactMessage, NewsletterSubscriber


class ContactMessageSerializer(serializers.ModelSerializer):
    """Public contact form submission."""

    class Meta:
        model = ContactMessage
        fields = [
            "id",
            "name",
            "email",
            "phone_number",
            "subject",
            "message",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_message(self, value):
        if len(value.strip()) < 10:
            raise serializers.ValidationError(
                "Please give us a bit more detail (at least 10 characters)."
            )
        return value.strip()


class NewsletterSubscriberSerializer(serializers.ModelSerializer):
    """
    Newsletter signup. Deliberately does NOT enforce unique=True at the
    serializer layer — resubscribing with an existing address should be a
    friendly no-op, not a validation error that leaks who is already
    subscribed. The view handles the get_or_create.
    """

    email = serializers.EmailField()

    class Meta:
        model = NewsletterSubscriber
        fields = ["id", "email", "created_at"]
        read_only_fields = ["id", "created_at"]
