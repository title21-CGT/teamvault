---
metadata:
  confidence: 0.8
  created: '2026-06-30T07:29:46.975310+00:00'
  source: /teamvault-publish
  tags:
  - field-library
  - form-engine
  - architecture
  - audit
  - rbac
  - decision
---

# Field Library: reusable form fields (copy-by-value + dedicated audit)

decision_type: decision · CGT manufacturing-workflow platform · shipped 2026-06-30 (cgt-backend#33, cgt-frontend#45)

## Context

The FormBuilder "Fields" tab needed a store of reusable, standalone form fields (the `FieldDefinition` shape) that can be defined once and inserted across many forms. Tracked as ClickUp 86ey2m0xb (backend) + 86ey2m10m (frontend). Before this, fields existed only inline inside each versioned `FormDefinition` — there was no standalone field store.

## Decision

**1. Copy-by-value with provenance.** Inserting a library field copies its full property set into a form and stamps a `libraryFieldId` on the embedded field. Editing or deleting a `LibraryField` never mutates already-published forms — they hold an independent snapshot. "Which forms use this field" is answered by a JSONB containment query on the provenance stamp, not a foreign key.

**2. Dedicated `FieldLibraryAudit` model.** Library-field CRUD is audited in a separate append-only model, NOT the existing 21 CFR Part 11 `AuditEntry`. Each mutation runs in a `prisma.$transaction` with its audit insert.

## Why

- The form engine already stores fields **copied by value** inside `FormDefinition.fields` JSONB, and form definitions are immutable/versioned. Link-by-reference would diverge from that model and risk silently changing published forms — unacceptable for a regulated (21 CFR Part 11) workflow.
- `AuditEntry` is FK-bound to `FormSubmission` (`submissionId` is required), so it cannot record a library-field mutation that has no submission. `FieldLibraryAudit` deliberately has **no FK** to `LibraryField`, so audit rows survive the field's deletion (true append-only).

## Implementation notes

- **RBAC:** `fields.read/create/edit/delete` (group `Forms`; `read`→USER_BASE, `read/create/edit`→SUPERVISOR_BASE, `delete`→full-access only). The catalog in `cgt-backend/src/auth/rbac/permissions.ts` is the source of truth, mirrored into `cgt-frontend/src/lib/permissions.ts`. Every new route carries an explicit decorator (the `route-access-coverage` guardrail enforces this).
- **Calculated fields:** validated at the library boundary only for "formula present + references ≥1 field" (siblings can't be resolved standalone); full ref/cycle validation still runs at form-save time. `formulaRefs` is derived server-side from the formula, never trusted from the client. On insert, the UI prompts the author to re-map each formula operand to a value-bearing field on the target form so the form stays valid.
- **List endpoint:** `GET /field-library?q=&fieldType=&skip=&take=` returns `{ items, total, typeCounts }` — server-side search (label/helpText, case-insensitive), per-type facet counts (`groupBy`), and offset pagination. Scales to a large library.
- **Sections interaction (IMPORTANT):** after the section-containers refactor (cgt-backend PR #32 / cgt-frontend PR #44), `FormDefinition.fields` is a `SectionDefinition[]` — sections own a nested `fields[]`. The usage query is therefore nested one level: `fields: { array_contains: [{ fields: [{ libraryFieldId: id }] }] }` (verified against real Postgres). Provenance round-trips through `toFieldDefinition` (save) and `fieldDefToFormField` (reload); library insertion appends into the active section. `CgtFieldType` gained `table` + `section`, but `LibraryField.fieldType` remains the 8-value Prisma `FieldType` enum (table/section are not creatable library fields).

## Related

- cgt-backend PR #33, cgt-frontend PR #45
- ClickUp 86ey2m0xb (backend), 86ey2m10m (frontend)
- Migration `20260628120000_add_field_library`