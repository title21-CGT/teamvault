---
created: 2026-07-06T00:00:00Z
source: manual
confidence: 0.9
author: Israel Abebe
decision_type: decision
kingdom: title21-cgt
palace: cgt-backend
wing: integration
hall: architecture
room: instrument-results
tunnels:
  - 2026-06-25-cgt-p06-consumer-client-decisions
tags:
  - cgt-p06
  - integration
  - instrument-results
  - webhook
  - phi
  - audit
---

# CGT-P06 integrations — module consolidation + inbound webhook receivers (2026-07)

## Context

Two follow-on efforts on the CGT-P06 integration area: a structural cleanup, then the new **push** (webhook) receiving path (ClickUp 86ey4x2yg). The area had grown iteratively without a full picture, and delivery was still pull-only. This entry updates the module-layout and PHI facts in `2026-06-25-cgt-p06-consumer-client-decisions.md`.

## Decisions

### 1. One integrations module; delete the dead "discovery" mapping
- Consolidated the two confusingly-named modules into a single `IntegrationsModule` under `src/integrations/`. The pull/read path (was `src/integration/`) is now `src/integrations/middleware/`; the source blueprint catalog (was `src/sources/`) folded in as `src/integrations/sources.controller.ts`.
- **Deleted the unused CSV "discovery" mapping** (`IntegrationField` / `IntegrationFieldMapping` models + `MappingDestination` / `MappingAction` enums + `discovery.util.ts`) — never wired to a route or the frontend. `InstrumentFieldMapping` (in `form-population/`) is now the sole field-mapping mechanism (instrument result value → form field).
- Moved demo data from runtime endpoints (`POST /integrations/demo[/reset]`, deleted) into `pnpm db:seed`.
- `Integration.viaMiddleware` now inherits from `Source.defaultViaMiddleware` on create.
- **Networks/tenants stay their own modules.** A `tenancy` consolidation was tried and reverted — they were already separate and correct.
- Frontend: redesigned Integrations list + detail pages; searchable form picker in the mapping tab (client-side filter, capped render — safe for thousands of forms); URL-driven (`?tab=`) tabs.

### 2. Inbound webhook receivers (push path)
- Two `@Public()` receivers: `POST /integrations/webhooks/:tenantId/instrument-results` and `.../cases`. Tenant is a **path param** (no user session; the pull-path `TenantContextGuard` doesn't apply).
- **Store-first**: every delivery is persisted to a new `WebhookNotification` table (raw body in a JSON column, `outcome=received`) BEFORE validation/processing, then updated to `processed` / `invalid`. Durable + replayable. This is the inbound source of truth — distinct from `IntegrationReadAudit`, which stays pull-only (no double-logging).
- Results receiver Zod-validates then **reuses `InstrumentResultsPersistenceService.ingest`** — idempotent on `(din, productCode, resultType, rowKey, version)`, latest-wins; re-delivery is a no-op.
- Cases receiver is **correlation-only for the POC**: upserts `InstrumentCorrelation (din, productCode) → transplant/patientMrn`, resolving the transplant by `patientMrn` else the last-updated one. `Transplant` is intentionally untouched (real design will match on a `productCode` the emitter sends).
- Frontend: a **Webhooks** tab (endpoint URLs, a delivery simulator to exercise the push path while the emitter is unbuilt, a delivery log + payload viewer). The signing-secret UI is present but disabled — a non-functional placeholder.

## PHI departure (important)

The 06-25 entry's **"No PHI on the wire"** invariant holds for the PULL path (only DIN + productCode cross the boundary). It is **explicitly departed from for the PUSH path**: the `cases` webhook receives patient + transplant PHI inbound, and the raw body is stored **at rest** in `WebhookNotification.payload`. Accepted for the POC. Follow-ups before production: retention policy, encryption at rest, PHI scrubbing of stored payloads. Tests use synthetic identifiers only.

## Deferred / out of scope (POC)

- Webhook **auth / signature (HMAC) verification** — receivers are `@Public()`; the `X-CGT-Signature` header + signing secret are UI-only placeholders.
- Async queue / retries / DLQ / delivery ordering.
- The emitter/push side (owned by another team; `integrations-service/` is currently GET-only with no push contract — our receiver Zod schemas are a best-guess provisional contract).
- Finalizing the real payload contract; the `cases` schema keeps `patient` / `transplant` as open blobs until agreed.

## Related

- `2026-06-25-cgt-p06-consumer-client-decisions.md` — original consumer/pull decisions this updates (module paths; the no-PHI-on-the-wire invariant now has a push exception).
- ClickUp 86ey2981h (consumer client), 86ey4x2yg (webhook receivers).
