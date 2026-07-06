---
metadata:
  confidence: 0.8
  created: '2026-07-06T12:29:56.795403+00:00'
  source: /teamvault-publish
  tags:
  - form-engine
  - conditional-visibility
  - decision
  - cgt-frontend
  - cgt-backend
---

---
created: 2026-07-06T13:00:00Z
source: manual
confidence: 0.9
author: Basliel Selamu
decision_type: decision
kingdom: title21-cgt
palace: cgt-backend
wing: form-engine
hall: architecture
room: conditional-visibility
tags:
  - form-engine
  - conditional-visibility
  - decision
---

# Conditional visibility — condition model + evaluator semantics (ClickUp 86ey59tnv)

## Decision

Fields and sections get an optional `visibility` rule in the `FormDefinition.fields` JSONB, shaped as a **two-level condition tree**:

```
visibility: {
  logic: 'and' | 'or',                 // joins the groups
  groups: [{ logic: 'and' | 'or',     // joins conditions inside the group (the "brackets")
             conditions: [{ sourceFieldId, operator, value }] }],
  action: 'show' | 'hide',
  require?: boolean                    // required while visible (show rules only in the UI)
}
```

Operators: `equals | notEquals | gt | gte | lt | lte` (comparisons only for number/date/calculated sources).

## Why

- **One connector per level, brackets are the only precedence mechanism** — `A AND B OR C` is inexpressible, so authored expressions are never ambiguous. Groups nest exactly one level; a single condition is one group with one condition (rendered bracket-free).
- **Uniform shape (groups-of-conditions, no unions)** keeps class-validator nested DTOs and the builder UI simple.
- Distinct from the sequencing mechanisms (`unlockedBy` locks, `gatedByPrevious`/`unlockedBySections` section gates): visibility **renders/hides**, sequencing **enables/disables**. They coexist on the same target.

## Evaluator semantics (mirrored FE/BE — keep in sync)

Canonical implementations: `cgt-backend/src/form-engine/evaluate-visibility.ts` and `cgt-frontend/src/lib/formSections.ts`.

- An **unanswered source makes its condition false** for every operator (show-targets stay hidden until the driver is answered) — EXCEPT boolean comparisons: an unanswered checkbox IS unchecked, so `equals 'false'` fires on fresh forms.
- `equals/notEquals` compare `String(a) === String(b)`; comparisons coerce numeric strings, then fall back to `Date.parse` for ISO dates.
- A **malformed rule (no `groups` array) means visible** — hiding on bad data would silently exempt required fields from completion.
- Hidden targets are **exempt from required-field checks** at completion (both FE `handleComplete` and BE `complete()`); stored values are retained while hidden.
- **Hidden targets never gate sequencing** — a hidden `unlockedBy` prerequisite, a hidden field inside a gating section, or a hidden prerequisite section is ignored, otherwise forms deadlock (found in adversarial review).
- **Cycle validation spans both levels**: field rules, section rules, and containment edges (a field is only visible while its section is). Rejected 422 on save and filtered from the builder's source pickers.

## Gotchas for future work

- `sanitizeVisibilityRule` (FE) strips conditions with empty `sourceFieldId` OR empty `value` at save time — half-edited rows must never persist (an `equals ''` condition permanently hides its target and silently exempts it from required checks).
- The DTO `value` is `string | number` guarded by `@ValidateIf(typeof !== 'number') @IsString()` — plain `@IsDefined()` let objects through as never-matching `'[object Object]'`.
- Multi-level nesting (groups inside groups), value-clearing on hide, and cross-form conditions were explicitly deferred.

## Related

- ClickUp 86ey59tnv (scope revision 2026-07-06: AND/OR + brackets + click-to-pick moved into v1).
- `2026-06-30-field-library-reusable-fields` — the FE↔BE FieldDefinition mirror + round-trip invariants this rides on.