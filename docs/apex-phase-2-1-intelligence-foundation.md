# Apex Phase 2.1 — Intelligent Response Foundation

Code-first execution, AI-assisted interpretation. The booking FSM, Twilio
webhook, Django tenancy, and OpenAI JSON seam from Phase 1 are unchanged.

## Architecture

Idle inbound messages (conversation state `idle`) now pass through
`apex_receptionist.intelligence` before any model call:

```
Trusted To-number routing (unchanged)
        │
        ▼
ConversationService.handle(business_id, sender, message)
        │
        ├─ active booking FSM ── deterministic collection / confirm
        │
        └─ idle ── ResponsePipeline.decide(business, message)
                    │
                    ├─ load TenantFacts for that business_id only
                    ├─ classify intent (keywords / FAQ overlap)
                    ├─ high-confidence fact answer or human handoff
                    └─ else optional AIService.respond (existing JSON actions)
```

New modules (no second engine, no new process):

| Module | Responsibility |
| --- | --- |
| `intelligence/facts.py` | Load one tenant's approved hours, contact, services, prices, FAQs |
| `intelligence/classifier.py` | Structured intent + confidence + method |
| `intelligence/templates.py` | Reply copy, separate from decision logic |
| `intelligence/engine.py` | Map intent + facts → reply; never invent missing data |
| `intelligence/pipeline.py` | Decision: start booking, deterministic, handoff, or AI |

`AIService` is not replaced. The pipeline never calls OpenAI. The conversation
service calls `AIService.respond` only when the decision is `ai`.

## Response decision flow

1. Flask webhook validates the Twilio signature and resolves the tenant from `To`.
2. `ConversationService` loads that business (no default-tenant fallback).
3. If the FSM is mid-booking, existing validators still own the turn.
4. If idle, the pipeline normalizes the message and classifies it.
5. Booking intent with high confidence starts the existing name → date → service flow.
6. Other high-confidence intents use stored facts or a missing-information reply.
7. Unknown / low-confidence messages use the existing AI seam, or a handoff when AI is disabled or fails.
8. Structured logs record tenant, intent, method, response type, `ai_required`, outcome, and duration.

## Supported intents

`GREETING`, `OPENING_HOURS`, `LOCATION`, `CONTACT`, `SERVICES`, `PRICING`,
`BOOKING`, `GENERAL_QUESTION` (approved FAQ overlap), `HUMAN_REQUEST`, `UNKNOWN`.

Classification payload: `intent`, `confidence` (0–1), `method`
(`keyword`, `faq_overlap`, `none`), optional `extracted` (matched service or FAQ).

Booking terms beat pricing terms so “how much to book PLC?” starts a booking
rather than quoting a price. A price word inside a location question does not
become `PRICING`. Confidence below 0.75 does not trigger a consequential action.

## Deterministic rules

- Answers use only the resolved tenant's `Business`, `Service`, and `FAQ` rows.
- Missing hours, address, contact, services, or prices produce a confirmation
  handoff: the bot does not invent facts.
- Prices are printed only when stored; unpriced services are listed as unknown.
- Templates never hard-code a business name.

## AI integration boundary

- Existing `AIService` JSON actions and tenant-scoped `ContextBuilder` remain.
- No tools, no SQL/Python/shell, no database writes from model output.
- `start_booking` from the model still requires `booking_enabled` in the FSM.
- Set `APEX_AI_ENABLED=false` to skip the model and hand off unknown questions.
- When `OPENAI_API_KEY` is unset or the provider fails, the existing safe
  handoff message is used. Tests never send paid requests.

## Tenant isolation

- Facts are loaded with the already-resolved `business_id`.
- `get_default_business()` is not used on this path.
- Customer messages cannot supply a tenant id.
- Cross-tenant tests cover hours, services, prices, and FAQ answers.

Authentication, CSRF, Twilio signatures, login rate limits, and webhook
idempotency are unchanged.

## Testing

```bash
. .venv/bin/activate
python -m pytest
python manage.py check
```

Phase 2.1 cases live in `tests/test_intelligence_foundation.py`. Existing FSM,
webhook, isolation, and AI tests stay enabled.

## Known limitations

- Keyword/FAQ matching is intentionally narrow; many questions still use AI.
- FAQ overlap is token-based, not semantic (no RAG).
- Pipeline outcomes are persisted in redacted form (Phase 2.2); token cost
  accounting remains Phase 2.4.
- Flask and Django sessions remain separate (Phase 1).
- One shared OpenAI/Twilio credential set for all tenants.

## Recommended next milestone

Phase 2.2 stores redacted pipeline outcomes
(`docs/apex-phase-2-2-intelligence-outcomes.md`). Next: collapse Flask/Django
HTTP onto Django without changing conversation behaviour. Do not add RAG,
billing, or new channels yet.
