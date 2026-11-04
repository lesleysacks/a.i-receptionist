from django.contrib import admin

from apps.intelligence.models import IntelligenceOutcome
from apps.intelligence.services import outcomes_for_user


@admin.register(IntelligenceOutcome)
class IntelligenceOutcomeAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "tenant",
        "intent",
        "decision",
        "response_type",
        "ai_required",
        "outcome",
        "duration_ms",
    )
    list_filter = ("intent", "decision", "ai_required", "outcome")
    readonly_fields = (
        "tenant",
        "receptionist_business_id",
        "intent",
        "classification_method",
        "confidence",
        "decision",
        "response_type",
        "ai_required",
        "outcome",
        "duration_ms",
        "created_at",
    )
    ordering = ("-created_at",)

    def get_queryset(self, request):
        return outcomes_for_user(request.user)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
