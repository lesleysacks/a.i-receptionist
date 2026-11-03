# Apex security controls (Phase 1)

## Controls in place

| Control | Where |
| --- | --- |
| Twilio `X-Twilio-Signature` | `apex_receptionist/adapters/twilio_webhook.py`; optional `WEBHOOK_BASE_URL` |
| CSRF on Flask dashboard forms | Flask-WTF (`CSRFProtect`) |
| CSRF on Django login | Django `CsrfViewMiddleware` |
| Password hashing | Django PBKDF2 via `User.set_password` |
| Session cookies | HttpOnly, SameSite=Lax, Secure in production |
| Login rate limit | Flask `/login` (Redis or process-local) |
| Tenant isolation | Membership queries; platform admin must send `X-Business-Id` |
| JSON admin auth | Session principal or `ADMIN_API_KEY` + `X-Business-Id` |
| Request size limit | `MAX_CONTENT_LENGTH` (default 64 KiB) |
| Structured logs | No request bodies; phone numbers masked |
| Audit trail | `AuditEvent` with redacted metadata |
| Webhook retries | `processed_webhooks` unique `(provider, MessageSid)` |

## Phase 0 findings addressed

| Finding | Status |
| --- | --- |
| Unauthenticated `/admin` and `/leads` | Fixed in recovered M5; still authenticated after Django wiring |
| Default-tenant attribution of chats | M5 routes by WhatsApp `To`; regression test forbids `get_default_business` on the webhook |
| PII in application logs | M5 JSON logs + mask helpers retained |
| README credential-shaped examples | Removed; rotate if those values were ever live |
| `businesses.json` contact PII | Replaced with synthetic placeholders |
| Twilio URL behind proxies | `WEBHOOK_BASE_URL` |
| No CSRF | Flask-WTF + Django CSRF |
| No request size limit | `MAX_CONTENT_LENGTH` |
| Duplicate webhook deliveries | MessageSid idempotency |

## Required rotation (do not print values)

If the historical `README-SETUP.md` examples were ever used as real Twilio
credentials, rotate:

- Twilio Auth Token (invalidates webhook signatures until env is updated)
- Any API keys derived from that account
- Owner notification destination if it was a personal number published in git

Git history of `main` may still contain those strings. Rotation in the provider
console is the remediation; rewriting git history is optional and disruptive.

## Secrets

Provide secrets only via environment variables or a secret manager. Names:

`SECRET_KEY`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `OPENAI_API_KEY`,
`ADMIN_API_KEY`, `ADMIN_PASSWORD`, `SENTRY_DSN`, `DATABASE_URL`, `REDIS_URL`.

Never log them. Never put them in docs, fixtures, or audit metadata.

## Remaining risks

- Shared provider credentials across tenants (Phase 4+ `ChannelIntegration`).
- Flask session and Django session are not yet unified.
- Operator `ADMIN_API_KEY` is a single shared secret; prefer platform-admin users.
- FAQ/knowledge text is still injected into the model prompt (prompt-injection
  within a tenant).
- No POPIA deletion/export workflow yet.
