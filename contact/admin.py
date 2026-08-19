from django.contrib import admin

from .models import ContactMessage, NewsletterSubscriber


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ["subject", "name", "email", "is_handled", "created_at"]
    list_filter = ["is_handled", "created_at"]
    list_editable = ["is_handled"]
    search_fields = ["name", "email", "subject", "message"]
    date_hierarchy = "created_at"
    readonly_fields = ["id", "name", "email", "phone_number", "subject", "message", "created_at"]
    actions = ["mark_handled", "mark_unhandled"]

    fieldsets = (
        ("Message", {"fields": ("subject", "message")}),
        ("From", {"fields": ("name", "email", "phone_number")}),
        ("Status", {"fields": ("is_handled", "created_at", "id")}),
    )

    def has_add_permission(self, request):
        # Messages only arrive through the public form.
        return False

    @admin.action(description="Mark selected as handled")
    def mark_handled(self, request, queryset):
        updated = queryset.update(is_handled=True)
        self.message_user(request, f"{updated} message(s) marked as handled.")

    @admin.action(description="Mark selected as not handled")
    def mark_unhandled(self, request, queryset):
        updated = queryset.update(is_handled=False)
        self.message_user(request, f"{updated} message(s) marked as not handled.")


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ["email", "is_active", "created_at"]
    list_filter = ["is_active", "created_at"]
    list_editable = ["is_active"]
    search_fields = ["email"]
    date_hierarchy = "created_at"
    readonly_fields = ["id", "created_at", "updated_at"]
