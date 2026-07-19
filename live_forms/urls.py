# live_forms/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import LiveFormLinkViewSet, LiveFormEntryViewSet, sheet_view

app_name = "live_forms"

router = DefaultRouter()
router.register(r"forms", LiveFormLinkViewSet, basename="form")
router.register(r"entries", LiveFormEntryViewSet, basename="entry")

urlpatterns = [
    # ── Interactive live sheet page (server-rendered) ─────────────────────
    # This whole urls.py is included from material/urls.py as:
    #   path("api/live_forms/", include("live_forms.urls"))
    # so this actually resolves at /api/live_forms/<slug>/, NOT /live-form/<slug>/.
    # NOTE: the React SPA has its own client-side implementation of this same
    # page at /live-form/:slug (src/pages/live_forms/LiveFormPage.jsx), which
    # is what every shareable link in the app actually points to. This
    # server-rendered view is not currently linked from anywhere in the
    # frontend — kept for any non-JS/embed use case, not dead code to remove
    # without checking with whoever added it.
    path("<slug:slug>/", sheet_view, name="sheet"),

    # ── DRF API endpoints ────────────────────────────────────────────────
    path("api/", include(router.urls)),
]

# ============================================================================
# AVAILABLE ENDPOINTS (as actually mounted from material/urls.py)
# ============================================================================
#
# SERVER-RENDERED SHEET PAGE:
# GET    /api/live_forms/<slug>/                             Server-rendered sheet.html (see note above)
#
# LIVE FORM LINKS:
# GET    /api/live_forms/api/forms/                          List (admin/owner)
# POST   /api/live_forms/api/forms/                          Create (admin)
# GET    /api/live_forms/api/forms/<slug>/                   Public detail + social proof + countdown seed
# PATCH  /api/live_forms/api/forms/<slug>/                   Update (admin)
# DELETE /api/live_forms/api/forms/<slug>/                   Delete (admin)
#
# PUBLIC ACTIONS:
# POST   /api/live_forms/api/forms/<slug>/submit/            Submit entry (public, throttled)
# GET    /api/live_forms/api/forms/<slug>/live_feed/         Real-time polling feed (public, throttled)
#        Optional: ?since=<ISO datetime>  → returns only new rows since that time
#
# ADMIN ACTIONS:
# GET    /api/live_forms/api/forms/<slug>/admin_entries/     Full entry list (admin only)
# GET    /api/live_forms/api/forms/<slug>/download_pdf/      Download PDF   (admin only)
# GET    /api/live_forms/api/forms/<slug>/download_word/     Download Word  (admin only)
# GET    /api/live_forms/api/forms/<slug>/download_excel/    Download Excel (admin only)
#
# ENTRIES:
# GET    /api/live_forms/api/entries/                        List all (admin only)
# GET    /api/live_forms/api/entries/<uuid>/                 Retrieve single entry (public)
# DELETE /api/live_forms/api/entries/<uuid>/                 Delete (admin only)