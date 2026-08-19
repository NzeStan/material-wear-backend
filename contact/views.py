import logging

from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status, views
from rest_framework.response import Response

from material.background_utils import send_email_async
from material.throttling import StrictAnonRateThrottle

from .models import NewsletterSubscriber
from .serializers import ContactMessageSerializer, NewsletterSubscriberSerializer

logger = logging.getLogger(__name__)


@extend_schema(tags=["Contact"])
class ContactMessageView(views.APIView):
    """Receive a message from the public Contact page."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = [StrictAnonRateThrottle]
    serializer_class = ContactMessageSerializer

    @extend_schema(
        summary="Submit a contact message",
        request=ContactMessageSerializer,
        responses={
            201: ContactMessageSerializer,
            400: OpenApiResponse(description="Validation error"),
            429: OpenApiResponse(description="Rate limited"),
        },
    )
    def post(self, request):
        serializer = ContactMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.save()

        logger.info(f"Contact message received from {message.email}: {message.subject}")

        # Notify the team. The message is already committed at this point, and
        # notification is best-effort: if it fails we log and still return 201,
        # because telling the visitor it failed would just make them resubmit
        # and create duplicates of a message we already have.
        try:
            send_email_async(
                subject=f"[Contact] {message.subject}",
                message=(
                    f"From: {message.name} <{message.email}>\n"
                    f"Phone: {message.phone_number or '—'}\n\n"
                    f"{message.message}"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[settings.COMPANY_EMAIL],
                # So hitting Reply in the inbox answers the customer directly
                # instead of bouncing off noreply@.
                reply_to=[message.email],
            )
        except Exception:
            logger.exception(
                f"Contact message {message.id} saved but team notification failed"
            )

        return Response(serializer.data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["Contact"])
class NewsletterSubscribeView(views.APIView):
    """Subscribe an email address to the newsletter (footer form)."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = [StrictAnonRateThrottle]
    serializer_class = NewsletterSubscriberSerializer

    @extend_schema(
        summary="Subscribe to the newsletter",
        request=NewsletterSubscriberSerializer,
        responses={
            201: OpenApiResponse(description="Subscribed"),
            200: OpenApiResponse(description="Already subscribed"),
            400: OpenApiResponse(description="Invalid email"),
            429: OpenApiResponse(description="Rate limited"),
        },
    )
    def post(self, request):
        serializer = NewsletterSubscriberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower().strip()

        subscriber, created = NewsletterSubscriber.objects.get_or_create(email=email)

        # Resubscribing after unsubscribing reactivates rather than erroring.
        if not created and not subscriber.is_active:
            subscriber.is_active = True
            subscriber.save(update_fields=["is_active", "updated_at"])
            created = True

        logger.info(
            f"Newsletter subscribe: {email} ({'new' if created else 'already subscribed'})"
        )

        return Response(
            {
                "detail": (
                    "Thanks for subscribing!"
                    if created
                    else "You're already subscribed."
                ),
                "email": email,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
