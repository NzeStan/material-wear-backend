# accounts/signals.py
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=get_user_model())
def auto_verify_admin_email(sender, instance, **kwargs):
    """Auto-verify the EmailAddress for any staff/superuser account.

    createsuperuser (and creating/promoting a staff user via Django admin)
    bypasses allauth's signup flow entirely, so no EmailAddress record ever
    gets created for them — and since ACCOUNT_EMAIL_VERIFICATION is
    mandatory in production, that silently blocks them from the regular
    customer-facing login even with correct credentials. Runs on every
    save (not just creation) so promoting an existing user to staff also
    gets covered, not just brand-new admin accounts.
    """
    if not (instance.is_staff or instance.is_superuser) or not instance.email:
        return

    from allauth.account.models import EmailAddress

    EmailAddress.objects.update_or_create(
        user=instance,
        email=instance.email,
        defaults={"verified": True, "primary": True},
    )
