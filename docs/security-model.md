# Security Model

> Phase 4 brief phase4-ops-002 fills this. Cross-references ADR-002 (auth), ADR-007 (custody), ADR-009 (idempotency).

## Threat surface (planned sections)

- Authentication: opaque sessions in Redis, magic-link rate limits, TOTP for value movements
- Authorization: per-context permissions, admin step-up
- Custody: KMS envelope encryption, AI never imports custody, prepared-action confirmation flow
- Idempotency: Redis SET NX EX 86400 + DB UNIQUE
- Webhook integrity: HMAC verification (Sumsub) + timestamp tolerance
- Logging: PII redaction
