# accounts/adapters.py
#
# BUG FOUND: The condition `if not user.pk` doesn't work with UUID primary keys
# because UUIDs are auto-generated on object creation (before save)
#
# FIX: Use `user._state.adding` to check if user is unsaved

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth import get_user_model
from django.utils.text import slugify
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
import logging
from rest_framework import serializers

User = get_user_model()
logger = logging.getLogger(__name__)


class CustomAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        """Allow or restrict signup."""
        return True

    def get_login_redirect_url(self, request):
        """Where allauth's own redirect-based login flow sends the browser
        once login succeeds and no explicit `next` was given. Used by the
        GitHub login button, and by Google when no popup client ID is
        configured — both customer-facing, so they belong on the storefront,
        not LOGIN_REDIRECT_URL (the Django admin, meant for staff)."""
        return settings.FRONTEND_URL

    def get_email_confirmation_url(self, request, emailconfirmation):
        """Where the confirmation email's link points. allauth's default
        builds a link to its own server-rendered Django page
        (/accounts/confirm-email/<key>/) — meaningless here since this is
        an API-only backend with no such template, so customers clicking
        the link landed on a broken/blank page. Point it at the frontend's
        VerifyEmail page instead, which calls back into
        /api/auth/social/registration/verify-email/ with the key."""
        frontend_base = settings.FRONTEND_URL.rstrip("/")
        return f"{frontend_base}/verify-email/{emailconfirmation.key}"

    def send_mail(self, template_prefix, email, context):
        """Custom email sending with HTML support.

        Wrapped in try/except: this backs every allauth-triggered email
        (signup confirmation, password reset, etc.), and an SMTP failure
        here must not take down the request that triggered it — the
        account was already created/logged in by the time this runs, so a
        mail outage shouldn't turn into a 500 for the user. Same reasoning
        as contact/views.py's send_email_async wrapping.
        """
        subject = render_to_string(f"{template_prefix}_subject.txt", context)
        subject = "".join(subject.splitlines())

        html_message = render_to_string(f"{template_prefix}_message.html", context)
        plain_message = strip_tags(html_message)

        from_email = self.get_from_email()

        try:
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=from_email,
                recipient_list=[email],
                html_message=html_message,
                fail_silently=False,
            )
            logger.info(f"Email sent to {email} with subject: {subject}")
        except Exception:
            logger.exception(f"Failed to send email to {email} (subject: {subject})")

    def save_user(self, request, user, form, commit=True):
        """Save user with additional fields."""
        user = super().save_user(request, user, form, commit=False)

        # Add any custom fields
        if commit:
            user.save()

        # Send welcome email
        if (
            settings.ACCOUNT_EMAIL_VERIFICATION != "mandatory"
            or user.emailaddress_set.filter(verified=True).exists()
        ):
            self.send_welcome_email(user)

        return user

    def send_welcome_email(self, user):
        """Send welcome email to new users."""
        # Build the login URL from FRONTEND_URL (the setting that actually exists
        # in settings.py). Fall back to an empty string so the URL is still valid
        # even if somehow FRONTEND_URL is missing.
        frontend_base = getattr(settings, "FRONTEND_URL", "").rstrip("/")
        login_url = f"{frontend_base}/login"

        context = {
            "user": user,
            "site_name": "MATERIAL WEAR",
            "login_url": login_url,
        }

        self.send_mail("account/email/welcome", user.email, context)


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        """Link social login to existing account instead of failing."""
        user = sociallogin.user

        if user.email:
            existing_users = User.objects.filter(email=user.email)
            if existing_users.exists():
                existing_user = existing_users.first()

                # Don't link if the existing user has a password (normal account)
                # unless explicitly requested
                if existing_user.has_usable_password():
                    # You might want to ask for confirmation here
                    # For now, we'll link automatically
                    pass

                sociallogin.connect(request, existing_user)
                # NOT setting state["process"] = "connect" here: that flag
                # tells allauth this is allauth's classic "manage connected
                # accounts" flow, which redirects to reverse
                # ("socialaccount_connections") on completion — a URL name
                # that only exists if allauth.socialaccount.urls is
                # included, which it isn't in this API-only project. That
                # caused every social login for an email with an existing
                # account to crash with NoReverseMatch. sociallogin.connect()
                # above already does the actual linking; this flag isn't
                # needed for that.

                # Ensure the email is marked as verified
                email_address = existing_user.emailaddress_set.filter(
                    email=user.email
                ).first()
                if email_address:
                    email_address.verified = True
                    email_address.primary = True
                    email_address.save()

                logger.info(f"Social account linked to existing user: {user.email}")
                return

        # FIX: Check if user is new (not yet saved) instead of checking pk
        # Works with UUID primary keys that auto-generate
        if user._state.adding and not user.username:
            base_username = slugify(user.email.split("@")[0])
            new_username = base_username
            count = 1
            while User.objects.filter(username=new_username).exists():
                new_username = f"{base_username}-{count}"
                count += 1
            user.username = new_username

    def save_user(self, request, sociallogin, form=None):
        """Save the user and mark their email as verified for social accounts."""
        user = super().save_user(request, sociallogin, form)

        # Mark email as verified for social accounts
        email_address = user.emailaddress_set.filter(email=user.email).first()
        if email_address:
            email_address.verified = True
            email_address.primary = True
            email_address.save()

        # Send welcome email for social signups
        if hasattr(self, "send_welcome_email"):
            self.send_welcome_email(user)

        logger.info(f"Social account created for user: {user.email}")
        return user

    def is_auto_signup_allowed(self, request, sociallogin):
        """Allow auto signup for social accounts."""
        return True

    def validate_disconnect(self, account, accounts):
        """Prevent disconnection of last social account if no password set."""
        user = account.user
        if not user.has_usable_password() and accounts.count() == 1:
            raise serializers.ValidationError(
                "Cannot disconnect last social account without setting a password"
            )