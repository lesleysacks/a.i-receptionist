# Apex Phase 2.2 — Persisted intelligence outcomes

Additive storage of redacted `ResponsePipeline` decisions so operators can
see how idle messages are classified. Customer replies, the booking FSM, Twilio
routing, and the OpenAI seam are unchanged. Flask and Django stay separate.

## Model

`apps.intelligence.IntelligenceOutcome` is a dedicated table. It is not an
`AuditEvent`. Audit events remain the security/admin trail (actor, action,
target). Outcomes are operational telemetry with a closed field list.

| Field | Purpose |
| --- | --- |
| `tenant` | Django tenant, resolved from `receptionist_business_id` |
| `receptionist_business_id` | Trusted SQLAlchemy business id from server-side routing |
| `created_at` | Timestamp (indexed) |
| `intent` | Classifier intent |
| `classification_method` | `keyword`, `faq_overlap`, or `none` |
| `confidence` | 0–1, three decimal places |
| `decision` | Pipeline decision (`deterministic`, `handoff`, `ai`, `start_booking`) |
| `response_type` | Narrow result label (`greeting`, `opening_hours`, `ai_fallback`, …) |
| `ai_required` | Whether the pipeline asked for the AI seam |
| `outcome` | `success`, `missing_information`, `handoff`, `fallback` |
| `duration_ms` | Pipeline decision time only (excludes the later AI call) |

Indexes: `(tenant, -created_at)` and `(receptionist_business_id, -created_at)`.

There is no message, phone, transcript, prompt, or JSON metadata column.

## Write path

`ResponsePipeline.decide` persists after it has already chosen the reply.
Tenant identity is the `business` already resolved from the WhatsApp `To`
number. The writer looks up `Tenant` by `receptionist_business_id`; it never
reads a tenant id from the customer.

If the insert fails, the exception is logged without the message body and the
customer still receives the reply.

Django admin lists outcomes as read-only. `outcomes_for_user` scopes rows to
active memberships. Platform administrators may read all rows through that
helper and Django admin (`/platform/django-admin/`). There is no public
analytics API or dashboard in this milestone.

## Migrations

Additive Django migration only:

```bash
python manage.py migrate intelligence
```

Rollback (disposable environments):

```bash
python manage.py migrate intelligence zero
```

Does not alter receptionist (Alembic) tables.

## Retention

Rows are kept indefinitely until an operator deletes the tenant (tenant FK is
`SET_NULL`, so the business id remains) or a later retention job is added.
No automated purge in Phase 2.2. Treat the table as operational telemetry, not
a chat archive.

## Known limitations

- Persistence is **synchronous** on the webhook thread: one small INSERT after
  the decision. A slow database adds latency; failures are swallowed.
- Only **idle pipeline** turns are stored. Mid-booking FSM steps are not.
- `ai_required` records that AI was requested, not token usage or cost
  (Phase 2.4).
- No operator UI beyond Django admin.

## Testing

```bash
. .venv/bin/activate
python -m pytest
python manage.py check
```

New cases: `tests/test_intelligence_outcomes.py`.
