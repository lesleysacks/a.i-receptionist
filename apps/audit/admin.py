from django.contrib import admin

from apps.audit.models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor", "tenant", "target_type", "target_id")
    list_filter = ("action",)
    search_fields = ("action", "target_id", "actor__email")
    readonly_fields = ("actor", "tenant", "action", "target_type", "target_id", "metadata", "ip_address", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
