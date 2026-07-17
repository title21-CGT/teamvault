---
metadata:
  confidence: 0.8
  created: '2026-07-17T05:11:18.349025+00:00'
  source: /teamvault-publish
  tags:
  - notifications
  - decision
  - architecture
  - cgt-backend
  - cgt-frontend
  - dead-code
  - prisma
---

---
created: 2026-07-17T10:00:00Z
source: /teamvault-publish
confidence: 0.9
author: Israel Abebe
decision_type: decision
kingdom: title21-cgt
palace: cgt-backend
wing: notifications
hall: architecture
room: counters
tags:
  - notifications
  - decision
  - architecture
  - cgt-backend
  - cgt-frontend
  - dead-code
  - prisma
---

# Notifications: per-module counters (cgt-backend + cgt-frontend)

## Context

The unread count only ever surfaced on the TopBar bell. The ask was to badge the dashboard side nav too, and to make the numbers **module-attributable**: Patients and Transplant now, more modules as they grow triggers. This updates `2026-07-15-notifications-architecture-decisions`, which anticipated a "sidebar badge" but did not have one on screen.

Two things surfaced during exploration that mattered more than the feature itself.

## The two traps

**1. The sidebar badge already existed, in a component nothing rendered.** `cgt-frontend/src/components/layout/Sidebar.tsx` called `useUnreadCount()` and rendered a correct badge on the Notifications item. `Layout.tsx` mounts only `TopBar`, so it never appeared. The nav actually on screen is the `<aside>` inside `DashboardPage.tsx`, built from `dashboardNav.ts`. `Sidebar.tsx` and `Navbar.tsx` were both unreferenced across `src/` and `e2e/` and are now **deleted**. Keeping two plausible-looking navs around is exactly how a working badge got written into the wrong one; that is the reusable lesson, not the deletion.

**2. `TRANSPLANT_DUE` was a dead enum member.** Declared in the schema and the `add_notifications` migration, and already routed by `notificationLink.ts` on the frontend, but **nothing in the backend ever emitted it**. A transplants badge would have read 0 forever while looking wired up. Grepping the enum found three "uses", all of them declarations or consumers. When checking whether a category works, grep for the **producer**, not the symbol.

## Decisions

1. **Group by `category`; derive the total from the same rows.** `unread-count` returns `{ count, byCategory }` from one `groupBy`, with `count` reduced from the grouped rows rather than a second `count()`. Two queries could drift; one cannot. `count` stays first and keeps its meaning, so the existing bell consumer was untouched.

2. **Two rows per intake, not one row counted twice.** `patient.new` opens a transplant case alongside the patient, so it now raises `TRANSPLANT_DUE` beside `PATIENT_INTAKE`. The alternative (one `PATIENT_INTAKE` row mapped onto both modules) was rejected: module badges would not sum to the bell total, and marking it read would clear both badges at once. Two rows means two independently dismissable facts. Cost: notification volume per intake doubles.

3. **No migration, and no `category` index.** The enum member already existed. `@@index([userId, readAt])` already narrows to one user's *unread* rows, which is a small set to group in memory. `[userId, readAt, category]` was considered and deliberately deferred as premature. The whole feature is migration-free, which is worth preserving.

4. **The category-to-module map lives on the frontend** (`src/lib/notificationNavBadges.ts`), next to `notificationLink.ts`. Same reasoning as the ids-not-URLs decision in the prior entry: the backend counts by category, and the frontend alone decides which categories a nav destination speaks for. A new mapping needs no backend change. Keys are exact paths, so `/transplants/calendar` deliberately stays bare.

5. **No new realtime path.** `useUnreadCount` already sits under the shared `notifications` query prefix that the socket invalidates on every push, so the badges update live for free. This is the single-prefix decision from the prior entry paying off: the feature was mostly one query shape plus one pure function.

6. **Webhook-only for now.** `POST /transplants` (manual create) stays silent. The audience is every enabled user, so the creator would be notified of their own action. Revisit alongside per-recipient targeting.

## Gotchas worth remembering

- **A read category disappears from `byCategory`; it does not report 0.** `groupBy` returns no row for a category with no unread rows, so consumers must default a missing key to 0. `navBadgeCount` does. Do not "simplify" that away. Found by running the real query against Postgres, not by the specs.
- **The specs mock Prisma, so they cannot catch a bad query shape.** `notification.groupBy` had to be added to `src/test-utils/prisma-mock.ts`; a green suite proves nothing about whether the query is valid. Verify `groupBy` shapes against a real database.
- **Frontend vitest runs in the node environment** (no jsdom/RTL), so badge logic in JSX gets no coverage at all. That is why `navBadgeCount` is pure and separate. Visual confirmation needs a throwaway harness plus headless Chrome; the dashboard is auth-gated, so seed a full-access session into `localStorage` under `cgt.auth.session` before mount (`AuthProvider` initialises from `getSession()`, and `AuthContext` is not exported).
- **No test ids in notification UI.** `e2e/pages/notifications.page.ts` documents the convention: role/accessible-name selectors, because the bell already exposes its count via `aria-label`. The badged nav cards follow suit ("Patients, 1 unread").
- **`Notification` vs `WebhookNotification`** are unrelated models, both touched in `webhooks.service.ts`. Easy to grep the wrong one.

## Related

- `2026-07-15-notifications-architecture-decisions`: the governing entry. Its single-query-prefix and ids-not-URLs decisions are what made this change small. Its "sidebar badge" claim was aspirational; this entry explains why.
- `2026-07-15-notifications-empty-user-table-trap`: still applies. An empty `User` table makes all of this silently produce nothing.
- ClickUp `86ey9nzyn` (BE) and `86ey9p1b2` (FE), both descriptions updated. PRs title21-CGT/cgt-backend#80 and title21-CGT/cgt-frontend#125.