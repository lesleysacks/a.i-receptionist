# Apex Phase 1 implementation

Phase 1 recovered the Milestone 5 receptionist engine and added a Django
management foundation. Conversation behaviour, Twilio webhooks, and OpenAI JSON
actions are unchanged except for security hardening.

## Architecture and module boundaries

```
apps/accounts     Django custom User, login/logout
apps/tenants      Tenant, Membership, access control
apps/audit        AuditEvent (no secrets or chat bodies)
apex/             Django project settings and URLs
apex_receptionist Domain package: FSM, AI, bookings, SQLAlchemy models
app.py / routes/  Flask HTTP adapter (webhook, dashboard, JSON admin)
receptionist_cli.py  Flask/SQLAlchemy bootstrap CLI
manage.py         Django CLI
```

Inbound WhatsApp still hits `POST /whatsapp`. Flask validates the Twilio
signature, routes by the `To` number, and calls `ConversationService`. Django
owns identity: Flask login authenticates against `accounts.User` and scopes
work through `Membership`.

`wsgi:app` dispatches receptionist paths to Flask and `/accounts/`, `/platform/`
to Django.

## Recovered M5 source

- Branch tip merged: `origin/cursor/deployable-observable-operable-c503`
  (`7ef7b8a`, draft PR #6, stacked on PRs #2–#5).
- Merge commit on this branch: `0758476`.
- Baseline after recovery: 86 passed, 2 skipped (no paid APIs).

## What Phase 1 added

- Custom Django user (email login) before the first Django migration.
- `Tenant` (`name`, `slug`, `status`, `service_mode` managed/self-service) linked
  to receptionist `businesses.id`.
- `Membership` roles: `PLATFORM_ADMIN`, `TENANT_ADMIN`, `TENANT_MEMBER`.
- `AuditEvent` for login, membership grants, operator API use, and privileged
  tenant access.
- Canonical `WEBHOOK_BASE_URL` for Twilio signatures, `MessageSid` idempotency,
  request size limits, safe 500 handler, PII-safe logs (already masked on M5).
- Credential-shaped README examples removed; `businesses.json` sanitised.

## Roles

| Role | Receptionist dashboard | JSON `/admin` | Django `/platform/` |
| --- | --- | --- | --- |
| `TENANT_MEMBER` | Read | GET only | No |
| `TENANT_ADMIN` | Read/write own tenant | Own tenant only | No |
| `PLATFORM_ADMIN` | Not implicit; must target a tenant | Requires `X-Business-Id` | Yes |

A user cannot read another tenant by submitting that tenant's id. Platform
admins must name the target business explicitly.

## Migrations

Two independent, additive schemas in the **same** PostgreSQL database:

1. Alembic (`alembic upgrade head`) — receptionist tables, including
   `processed_webhooks`.
2. Django (`python manage.py migrate`) — accounts, tenants, audit.

Neither drops receptionist data. The unused SQLAlchemy `admin_users` table is
kept so existing databases are not destroyed. New logins write Django `User`
rows only.

**Rollback:** `python manage.py migrate accounts zero` (or a specific Django
revision) then `alembic downgrade 379ee94dc59e` to drop `processed_webhooks`.
Do this only on disposable environments.

**AdminUser → User:** there is no automatic copy. Recreate operators with
`python receptionist_cli.py create-admin` or
`python manage.py create_platform_admin`.

## Known limitations (Phase 2+)

- Flask and Django still use separate session cookies.
- One shared Twilio/OpenAI credential set for all tenants.
- No billing, public signup, RAG, or extra channels.
- Timezone on appointment rows remains naive; reminder comparison uses UTC naive.
- Dual HTTP frameworks should be collapsed in Phase 3.
