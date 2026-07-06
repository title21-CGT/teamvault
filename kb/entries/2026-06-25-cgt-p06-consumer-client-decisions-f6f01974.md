---
metadata:
  confidence: 0.8
  created: '2026-06-25T09:58:42.840657+00:00'
  source: /teamvault-publish
  tags:
  - cgt-p06
  - integration
  - instrument-results
  - audit
  - contract-first
  - decision
---

---
created: 2026-06-25T12:00:00Z
source: manual
confidence: 0.9
author: Israel Abebe
decision_type: decision
kingdom: title21-cgt
palace: cgt-backend
wing: integration
hall: architecture
room: instrument-results
tags:
  - cgt-p06
  - integration
  - instrument-results
  - audit
  - contract-first
---

# CGT-P06 consumer client — architecture decisions (cgt-backend)

## Context

ClickUp `86ey2981h` built the `cgt-backend` consumer side of the CGT-P06 instrument integration API: read normalized instrument results by **DIN + product code**, correlate to our patients/orders, persist, and audit. The ticket assumed three artifacts/structures that did not exist locally, so we made deliberate calls.

## Decisions

1. **Vendor the contract.** The real CGT-P06 repo (`api/openapi.yaml` + mock server) is not in the workspace. We committed a v1 stand-in at `cgt-backend/api/contracts/p06.openapi.yaml`, generate runtime validators (zod) from it, and gate drift with a test. **Obligation: re-sync this file when the real P06 contract is published.** Switching mock→prod is env-only (`INTEGRATION_API_BASE_URL`), no code change.

2. **Read-audit gets its own model.** AC said "reuse/extend `AuditEntry`," but `AuditEntry` is a required FK to `FormSubmission` and is shaped for 21 CFR Part 11 field-change events — there is no slot for a contract-key API read with no submission. We added a dedicated `IntegrationReadAudit` model instead.

3. **Correlation gets its own table.** `(din, productCode)` did not exist on `FormSubmission`/`Transplant` (chart key is `patientMrn`). We added an `InstrumentCorrelation` table mapping `(din, productCode) → transplantId/patientMrn`; persisted results carry a nullable FK to it.

## Why

Keeps the Part 11 form-audit trail clean and queryable; isolates the correlation concern from the patient/order model; and unblocks contract-first development without the upstream P06 repo. Ingest (correlate → persist → back-fill → terminal audit) is wrapped in a single transaction so a partial-persistence failure can never leave an audited read with no terminal outcome.

## Impact / known v1 limitations

- AC #10 (mock-server e2e) is **fixture-approximated** (`__fixtures__/` replay) until the real P06 mock server is reachable.
- Contract-drift test checks `components.schemas` field-sets + required/optional only — **not** paths, params, or status→schema bindings.
- zod schemas are **non-strict** (additive upstream fields pass silently — chosen for forward-compat); pagination is unsupported (`total != items.length` → `ContractValidationError`).
- No PHI on the wire: requests carry only DIN + product code; tests use synthetic identifiers (e.g. `din: "TEST-A1234567890123"`). Verified by the HIPAA pack reviewer.

## Open

- Re-sync the vendored contract when CGT-P06 ships `api/openapi.yaml`; revisit non-strict zod + path-level drift coverage at that point.
- "Latest-wins" is a read-time convention (max `version`); no materialized `isLatest` flag yet — add one if reads get hot.

## Related

- ClickUp 86ey2981h; PR title21-CGT/cgt-backend#30.
- Related P06-adjacent services: CGT-P02 (audit/retention), CGT-P03 (service identity/secrets).

## Update — 2026-07-06

Two follow-ons changed some facts here — see `2026-07-06-cgt-p06-integrations-consolidation-and-webhooks.md`:

- **Module paths moved.** The read/consumer path is now `src/integrations/middleware/` (was `src/integration/`), under a single `IntegrationsModule`. The unused CSV "discovery" mapping (`IntegrationField` / `IntegrationFieldMapping`) was deleted; `InstrumentFieldMapping` is the sole field-mapping mechanism. `IntegrationReadAudit` and `InstrumentCorrelation` (decisions 2 and 3 above) are unchanged, just relocated with the module.
- **"No PHI on the wire" now has a push exception.** Still true for the pull path (DIN + productCode only). A new inbound `cases` webhook receives patient/transplant PHI and stores the raw body at rest in a new `WebhookNotification` table — accepted for the POC; retention / encryption / scrubbing are open follow-ups.