---
metadata:
  confidence: 0.8
  created: '2026-07-15T07:52:19.341674+00:00'
  source: /teamvault-publish
  tags:
  - notifications
  - websocket
  - rbac
  - architecture
  - decision
  - cgt-backend
  - cgt-frontend
---

---
created: 2026-07-15T08:00:00Z
source: /teamvault-publish
confidence: 0.9
author: Israel Abebe
decision_type: decision
kingdom: title21-cgt
palace: cgt-backend
wing: notifications
hall: architecture
room: _
tunnels:
  - 2026-06-25-cgt-p06-consumer-client-decisions
tags:
  - notifications
  - websocket
  - rbac
  - architecture
---

# Notifications — architecture decisions (cgt-backend + cgt-frontend)

## Context

ClickUp `86ey9nzyn` (backend) + `86ey9p1b2` (frontend) replaced the frontend's hardcoded `mockAlerts` with a real in-app notifications feature: a programmatic trigger surface other modules call, a caller-scoped REST read API, and a socket.io gateway that pushes to open sessions. Several ticket assumptions did not survive contact with the codebase, so we made deliberate calls.

## Decisions

1. **Auth-only gating, not `alerts.view`.** The ACs said gate the route/bell on `alerts.view`. That key exists in the permission catalog but is in **no role baseline**, so gating on it would have hidden the feature from essentially everyone. The routes are `@AuthOnly` (the decorator that declares "authenticated, no specific permission" and satisfies the `route-access-coverage` guardrail). Per-user isolation is enforced in the **service**, which scopes every query to the caller's `userId` — not by RBAC.

2. **No audit model.** ACs said write an `AuditEntry` per mark-read. Marking your own notification read is not a 21 CFR Part 11 event, and `AuditEntry` is a required FK to `FormSubmission` so it could not have been reused anyway — the same wall CGT-P06 hit (see its Decision #2, which added `IntegrationReadAudit`). We wrote no audit table at all. If notification read-state ever needs a trail, it needs its own model.

3. **`payload` carries ids, not URLs.** Notifications are actionable (click → patient/case page). The backend stores routing **context** (`patientMrn` / `transplantId` / `din`) in the existing `payload` JSON; the frontend maps `category + payload → route`. Storing a URL would have rotted immediately: this very feature renamed `/alerts` → `/notifications`, which would have dead-linked every stored row.

4. **The WebSocket handshake reuses the REST verification pipeline.** Rather than a second auth path, we extracted `AccessTokenAuthenticator` out of `CognitoAuthGuard` (verify → resolve/bind local user → `RequestUser`). Both the HTTP guard and the gateway call it. The gateway rejects sockets whose principal has no local user row — such a principal cannot own notifications.

5. **Emit after commit, never inside the transaction.** `NotificationsService.create` persists, then pushes. A push from inside a transaction can announce a row that later rolls back.

6. **Triggers are best-effort.** The inbound webhooks (`patient.new` → `PATIENT_INTAKE`, `instrument.result` → `LAB_RESULT`) raise notifications in a try/catch that logs but never rethrows. A notification problem must never turn a good delivery into an error — same posture as the existing auto-populate step.

## Why

The gating and audit decisions both come from the same place: the ticket described a system that did not match the code. Verifying the baseline (`alerts.view` in no role; `AuditEntry` FK-bound) turned two "just follow the AC" tasks into deliberate departures. The ids-not-URLs call is the one most likely to be quietly reversed by a future contributor — the rename that proves the point happened in the same PR pair, so it is worth stating loudly.

## What changed

- `Notification` model (single `userId` FK → `User`), `NotificationType` / `NotificationCategory` enums, `add_notifications` migration.
- `NotificationsService` is `NotificationsModule`'s **only export** — callers trigger notifications through it and never touch the table.
- `NotificationsGateway` on `/ws/notifications`, per-user rooms, `notification:new` / `notification:read`.
- Frontend: one TanStack Query key prefix shared by bell, sidebar badge, popover and page, so they cannot disagree; WS events invalidate it.

## Open / known v1 limitations

- **Audience is every enabled user.** `User` has no `tenantId`, and `Patient`/`Transplant` carry no owner/assignee — so neither tenant-scoped nor "responsible clinician" targeting is expressible today. A `createForPermission(permKey, …)` helper exists but is not the default. There is a `TODO(tenant)` at the resolver; scope it once `User.tenantId` lands.
- **Delivery is best-effort, not durable.** No open socket ⇒ the user sees it on next `GET /notifications`. The WS is a push convenience, not a queue.
- Frontend tests run in vitest's **node** environment (no jsdom/RTL), so component render tests are not possible; the socket wiring is deliberately extracted into a pure `createNotificationsSocket` factory to keep it testable.

## Related

- `2026-06-25-cgt-p06-consumer-client-decisions-f6f01974.md` — Decision #2 (dedicated audit model) is the governing precedent for #2 above.
- `2026-07-15-notifications-empty-user-table-trap.md` — the operational trap that made this feature look broken on a fresh environment.
- ClickUp `86ey9nzyn` / `86ey9p1b2`; PRs title21-CGT/cgt-backend#73 and title21-CGT/cgt-frontend#109.