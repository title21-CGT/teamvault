---
metadata:
  confidence: 0.8
  created: '2026-07-20T18:17:38.185897+00:00'
  source: /teamvault-publish
  tags:
  - form-engine
  - versioning
  - procedures
  - audit
  - decision
  - cgt-frontend
  - cgt-backend
---

---
author: Basliel Selamu
decision_type: decision
kingdom: title21-cgt
palace: cgt-backend
wing: form-engine
hall: architecture
room: versioning
links:
  - ClickUp 86eybvqgn
  - 2026-06-30-field-library-reusable-fields (audit-model precedent)
---

# Form & transplant template version control (ClickUp 86eybvqgn)

## Decision

Versioning for `FormDefinition` and `Procedure` (UI: "transplant template") is keyed by a new **`familyId`** column — NOT by name. `familyId` = the first version's own id for service-created rows (backfilled `= id`; DB default `gen_random_uuid()` covers raw-SQL inserts, which become single-member families — the seed produces such rows, so never rely on `familyId === id`). **`@@unique([familyId, version])`** on both models makes concurrent version-mints impossible; services map P2002 → 409.

New versions are minted ONLY by explicit signed endpoints — `POST /form-definitions/:id/versions` (carries the full edited definition) and `POST /procedures/:id/versions` (copies steps/edges, swapping exactly one form ref to a newer ACTIVE version of the same family). `PUT /form-definitions/:id` remains strictly in-place (the 86ey86v2g contract still holds); the builder UI now routes content saves through the version endpoint via a "Save as New Version" dialog.

Lifecycle: the previously dormant `FormDefinition.active` boolean was adopted (Procedure gained one). Rules: inactivating a form version used by an ACTIVE template → 409; inactivating a template cascades to form versions referenced by no other active procedure (cascade computed INSIDE the `$transaction`); inactive versions are never offered by version checks or the sequence-editor picker (which shows only the latest active version per family, using the server's `latestActiveVersion` annotation).

Audit: a dedicated append-only **`VersionAudit`** model (no FKs, modeled on `MaintenanceEventAudit` — `AuditEntry` is FK-bound to `FormSubmission` and cannot record these events). Events: `version_created`, `form_ref_updated`, `activated`, `inactivated`, `cascade_inactivated`; `signedBy` is required (name-confirmation e-signature — deliberately NO password, matching the renderer's existing signature pattern, which was extracted into the reusable `cgt-frontend/src/components/signature/SignatureDialog.tsx`).

## Gotchas for future work

- `GET /procedures` is **conditionally paginated**: legacy flat array with no params, `{ items, total }` when `skip`/`take` present — keeps the four existing flat-list callers working.
- `formsApi.createDefinitionVersion` inherits `isTestData` from the source row so e2e-created families sweep together.
- Version copies deep-copy `FormDefinition.fields` as `SectionDefinition[]` (post section-containers refactor).
- Display "unique IDs" (`FRM-XXXXX-V2` / `TPL-XXXXX-V2`) are derived client-side from familyId (`cgt-frontend/src/lib/versioning.ts`) — they are NOT stored.
- **Open product question:** `PUT /procedures/:id/sequence` and `PATCH` are still allowed on superseded/inactive template versions — historical versions are not frozen. Flagged in review; needs a product decision.