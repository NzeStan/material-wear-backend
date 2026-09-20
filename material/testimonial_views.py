from rest_framework.response import Response
from rest_framework.views import APIView
from testimonials.api.permissions import CanModerateTestimonial
from testimonials.models import Testimonial


class ModeratorTestimonialStatsView(APIView):
    """
    Moderation statistics (pending / rejected counts etc.) — moderators only.

    django-testimonials 1.0.1's own `stats` action declares
    CanModerateTestimonial, but the viewset's get_permissions() overrides
    per-action permission_classes and falls back to IsAuthenticatedOrReadOnly,
    so anonymous visitors could read it. This route is registered ahead of the
    package's router in material/urls.py to shadow it; drop both once the
    package's get_permissions() lists `stats` with the moderator actions.
    """

    permission_classes = [CanModerateTestimonial]

    def get(self, request):
        return Response(Testimonial.objects.get_stats())
