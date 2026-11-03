from django.contrib import admin

from apps.tenants.models import Membership, Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "status", "service_mode", "receptionist_business_id", "updated_at")
    search_fields = ("name", "slug")
    list_filter = ("status", "service_mode")


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "tenant", "role", "status", "created_at")
    list_filter = ("role", "status")
    search_fields = ("user__email", "tenant__slug")
