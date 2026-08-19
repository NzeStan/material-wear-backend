# contact/urls.py
from django.urls import path

from .views import ContactMessageView, NewsletterSubscribeView

app_name = "contact"

urlpatterns = [
    path("message/", ContactMessageView.as_view(), name="message"),
    path("subscribe/", NewsletterSubscribeView.as_view(), name="subscribe"),
]

# ============================================================================
# AVAILABLE ENDPOINTS (mounted at /api/contact/ from material/urls.py)
# ============================================================================
# POST   /api/contact/message/     # Contact page form (public, 50/hour per IP)
#        Body: { name, email, phone_number?, subject, message }
#
# POST   /api/contact/subscribe/   # Footer newsletter signup (public, 50/hour)
#        Body: { email }
#        201 = newly subscribed, 200 = already subscribed (not an error)
#
# Submissions are readable by staff in Django admin under "Contact".
