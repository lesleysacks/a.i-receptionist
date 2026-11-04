"""Redacted ResponsePipeline outcomes for operator analysis.

This is not an audit log. Security and admin actions stay on AuditEvent.
Rows never include message bodies, phone numbers, transcripts, or secrets.
"""

from __future__ import annotations

from django.db import models


class IntelligenceOutcome(models.Model):
    """One idle-message pipeline decision, scoped to a tenant."""

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="intelligence_outcomes",
    )
    receptionist_business_id = models.IntegerField(
        db_index=True,
        help_text="Trusted SQLAlchemy businesses.id from server-side routing.",
    )
    intent = models.CharField(max_length=32, db_index=True)
    classification_method = models.CharField(max_length=32)
    confidence = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    decision = models.CharField(max_length=32)
    response_type = models.CharField(max_length=32)
    ai_required = models.BooleanField(default=False)
    outcome = models.CharField(max_length=32)
    duration_ms = models.DecimalField(max_digits=10, decimal_places=1, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("tenant", "-created_at"), name="intel_outcome_tenant_ts"),
            models.Index(fields=("receptionist_business_id", "-created_at"), name="intel_outcome_biz_ts"),
        )

    def __str__(self) -> str:
        return f"{self.intent} {self.decision} @ {self.created_at}"
