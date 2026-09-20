from urllib.parse import quote
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django.shortcuts import get_object_or_404
from .models import ReferrerProfile, PromotionalMedia
from .serializers import (
    ReferrerProfileSerializer,
    PromotionalMediaSerializer,
    SharePayloadSerializer,
)
from django.conf import settings

# Used when no active promotional media has marketing text yet. WhatsApp-style
# formatting: *bold*, _italic_; blank lines are kept.
DEFAULT_MARKETING_TEXT = (
    "🔥 *NYSC kits, church wear & NYSC tour packages — all in one place!* 🔥\n"
    "\n"
    "Serving in NYSC? Planning a church programme or a group order? "
    "Material Wear Limited has you covered 🇳🇬\n"
    "\n"
    "✅ NYSC kits — Khaki, Vest & Cap 👕\n"
    "✅ Church & programme shirts, jackets and polos ⛪\n"
    "✅ NYSC tour packages for all 37 states 🗺️\n"
    "✅ Group & bulk orders for your class, church or team 🤝\n"
    "✅ Order online in minutes with secure payment 🔒\n"
    "\n"
    "_Quality you can trust — Material Wear Limited (RC 9161164)_"
)


class ReferrerProfileViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing referrer profiles.

    - list: Admin only - list all referrer profiles
    - create: Authenticated users can create their profile (one per user)
    - retrieve: Users can view their own profile
    - update/partial_update: Users can update their own profile
    - destroy: Admin only
    """

    serializer_class = ReferrerProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return profiles based on user permissions"""
        if getattr(self, 'swagger_fake_view', False):
            return ReferrerProfile.objects.none()
        user = self.request.user
        if user.is_staff:
            return ReferrerProfile.objects.all().select_related("user")
        return ReferrerProfile.objects.filter(user=user).select_related("user")

    def get_permissions(self):
        """Set permissions based on action"""
        if self.action in ["list", "destroy", "by_code"]:
            return [IsAdminUser()]
        return [IsAuthenticated()]

    @action(
        detail=False,
        methods=["get"],
        url_path=r"by-code/(?P<code>[A-Za-z0-9]{8})",
        url_name="by-code",
    )
    def by_code(self, request, code=None):
        """Admin only: look up a referrer (and their details) by referral code."""
        profile = get_object_or_404(
            ReferrerProfile.objects.select_related("user"),
            referral_code=code.upper(),
        )
        return Response(self.get_serializer(profile).data)

    def create(self, request, *args, **kwargs):
        """Create a referrer profile for the authenticated user"""
        # Check if user already has a profile
        if ReferrerProfile.objects.filter(user=request.user).exists():
            return Response(
                {
                    "detail": "You already have a referrer profile. Each user can only have one profile."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )

    @action(detail=False, methods=["get"], url_path="me")
    def get_my_profile(self, request):
        """Get the authenticated user's referrer profile"""
        try:
            profile = ReferrerProfile.objects.select_related("user").get(
                user=request.user
            )
            serializer = self.get_serializer(profile)
            return Response(serializer.data)
        except ReferrerProfile.DoesNotExist:
            return Response(
                {"detail": "You do not have a referrer profile yet."},
                status=status.HTTP_404_NOT_FOUND,
            )

    @action(detail=False, methods=["patch", "put"], url_path="me/update")
    def update_my_profile(self, request):
        """Update the authenticated user's referrer profile"""
        try:
            profile = ReferrerProfile.objects.get(user=request.user)
        except ReferrerProfile.DoesNotExist:
            return Response(
                {"detail": "You do not have a referrer profile yet."},
                status=status.HTTP_404_NOT_FOUND,
            )

        partial = request.method == "PATCH"
        serializer = self.get_serializer(profile, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class PromotionalMediaViewSet(viewsets.ModelViewSet):
    """
    ViewSet for promotional media.

    - list: Authenticated users can view active media
    - retrieve: Authenticated users can view specific media
    - create/update/destroy: Admin only
    """

    serializer_class = PromotionalMediaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return active media for regular users, all media for admins"""
        user = self.request.user
        queryset = PromotionalMedia.objects.all()

        if not user.is_staff:
            queryset = queryset.filter(is_active=True)

        return queryset.select_related("created_by")

    def get_permissions(self):
        """Admin-only for create, update, delete operations"""
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [IsAdminUser()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        """Set created_by to the current admin user"""
        serializer.save(created_by=self.request.user)


class SharePayloadViewSet(viewsets.ViewSet):
    """
    ViewSet for generating share payloads for referrers.

    Returns promotional media, marketing text, and WhatsApp deep link
    with the referrer's code embedded.
    """

    serializer_class = SharePayloadSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get"], url_path="generate")
    def generate_payload(self, request):
        """
        Generate complete share payload for the authenticated referrer.

        Returns:
        - promotional_media: List of active promotional media
        - referral_code: User's unique referral code
        - whatsapp_link: WhatsApp deep link with pre-filled message
        - share_message: Combined marketing text with referral code
        """
        # Get user's referrer profile
        try:
            profile = ReferrerProfile.objects.select_related("user").get(
                user=request.user, is_active=True
            )
        except ReferrerProfile.DoesNotExist:
            return Response(
                {
                    "detail": "You do not have an active referrer profile. Please create one first."
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Get active promotional media
        media = PromotionalMedia.objects.filter(is_active=True).order_by(
            "order", "-created_at"
        )

        share_footer = self._build_share_footer(profile.referral_code)

        # Build share message
        share_message = self._build_share_message(media, share_footer)

        # Generate WhatsApp deep link
        whatsapp_link = self._generate_whatsapp_link(share_message)

        # Prepare response
        payload = {
            "promotional_media": PromotionalMediaSerializer(media, many=True).data,
            "referral_code": profile.referral_code,
            "whatsapp_link": whatsapp_link,
            "share_message": share_message,
            "share_footer": share_footer,
        }

        return Response(payload)

    def _build_share_footer(self, referral_code):
        """Referral code + shop link, appended to every message a referrer shares."""
        site_url = str(getattr(settings, "FRONTEND_URL", "")).rstrip("/")
        lines = [f"💎 Use my referral code: *{referral_code}*"]
        if site_url:
            lines.append(f"🛍️ Shop here: {site_url}")
        return "\n".join(lines)

    def _build_share_message(self, media, share_footer):
        """
        Build the complete share message: the first active item's marketing
        text (admin controls which via the `order` field) plus the footer.

        Joining every active item's text into one message produced a wall of
        text as soon as more than one flyer/video existed.
        """
        base_message = next(
            (m.marketing_text.strip() for m in media if m.marketing_text.strip()),
            DEFAULT_MARKETING_TEXT,
        )
        return f"{base_message}\n\n{share_footer}"

    def _generate_whatsapp_link(self, message):
        """
        WhatsApp deep link with the message pre-filled and NO fixed recipient,
        so WhatsApp lets the referrer pick who to send it to.

        (This previously embedded the business WHATSAPP_NUMBER, which opened a
        chat with Material Wear's own number instead of the referrer's friends.)
        """
        return f"https://wa.me/?text={quote(message)}"
