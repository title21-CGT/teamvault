---
metadata:
  confidence: 0.8
  created: '2026-07-15T07:54:29.646194+00:00'
  source: /teamvault-publish
  tags:
  - notifications
  - rbac
  - cognito
  - user-provisioning
  - debugging
  - gotcha
  - cgt-backend
---

---
created: 2026-07-15T08:30:00Z
source: /teamvault-publish
confidence: 0.95
author: Israel Abebe
decision_type: pattern
kingdom: title21-cgt
palace: cgt-backend
wing: notifications
hall: debugging
room: _
tunnels:
  - 2026-07-15-notifications-architecture-decisions
tags:
  - notifications
  - rbac
  - cognito
  - user-provisioning
  - gotcha
---

# Notifications silently produce nothing on a fresh environment (empty User table)

## Symptom

Inbound webhooks process correctly — patients and transplant cases get created, `WebhookNotification` rows show `outcome: processed` — but **zero `Notification` rows appear**, the bell stays empty, and there is no error anywhere.

## Root cause

Notifications are addressed to **local `User` rows**. `createForAllUsers` resolves its audience with `user.findMany({ where: { enabled: true } })`. On a fresh environment that returns `[]`, the fan-out targets nobody, and creating zero notifications is not an error — so it succeeded silently.

The reason the table is empty is the non-obvious part: **`CognitoAuthGuard` does not auto-provision local `User` rows.** A Cognito principal with no DB row is resolved purely from token claims with `userId: null` ("strictly a read-only fallback"). You can log in, hold full access via your Cognito group, and use the whole app while the `User` table has **zero rows**. The `User` table is only populated by an explicit sync/import.

Two consequences, not one:
1. No recipients ⇒ no notifications are ever created.
2. Even if they existed, **your own** principal has `userId: null` ⇒ `list` / `unreadCount` return empty/0 and the WS gateway rejects your socket ("No user profile is bound to this account").

## How to confirm in 10 seconds

```sql
SELECT count(*) FILTER (WHERE enabled) AS enabled_users FROM "User";  -- 0 ⇒ this is your bug
SELECT count(*) FROM "Notification";
```

Do not confuse **`WebhookNotification`** (raw inbound delivery log — written on every webhook) with **`Notification`** (in-app). Rows in the first prove nothing about the second; the similar names cost real debugging time.

## Fix: populate the User table

There is **no Sync/Import button** — the endpoints exist but were never wired into the frontend. They are API-only.

| Path | Needs AWS credentials? |
|---|---|
| "Add user" button → `cognito.createAdmin` | **Yes** — and it throws `ConflictException` for an email that already exists in Cognito, so it cannot link *your* account |
| `POST /api/users/sync` → `listUsersForSync` | **Yes** (`cognito-idp:ListUsers`) |
| `POST /api/users/import` | **No** — caller supplies `{ email, sub, group }`; no server-side Cognito call |

`POST /api/users/import` is the path that works with **no AWS setup at all**. It binds `cognitoSub` directly, so the guard resolves you by sub afterwards without ever calling Cognito.

Login itself needs no AWS credentials: `aws-jwt-verify` fetches the pool's public JWKS over plain HTTPS. That is why sign-in works on a machine with no credentials while every admin operation fails with `CredentialsProviderError: Could not load credentials from any providers`.

After a row exists, **reload the SPA** — `AuthProvider` re-fetches `/auth/me` on mount, and the cached `cgt.auth.session` in localStorage still carries the old `userId: null` that the bell and the socket both depend on.

## `RBAC_BOOTSTRAP_ADMINS` — undocumented, and subtler than it looks

Not in `.env.example`; it only appears in the auth guard. It grants SuperAdmin `fullAccess` to a principal with **no DB row**, which is the intended escape hatch for exactly this bootstrap state. Two traps:

- It is **only consulted when there is no DB row** (`if (dbUser) return fromDbUser(...)`). Once a user row exists it is dead code.
- It matches against `resolvedEmail ?? claims.username`, and `resolvedEmail` comes from a Cognito lookup that **needs AWS credentials**. Without them it degrades to `null`, so the match falls back to the token's `username` claim — which in an email-alias pool is a UUID, not an email. Putting an email in the var then silently never matches. Decode your access token and use whatever `username` actually is.

## What changed

The silent failure is now loud: `createForUsers` logs a warning naming the category when the audience is empty, and the webhook trigger logs (rather than swallows) a failed notification. An empty audience is nearly always a misconfiguration, not an intended no-op.

## Related

- `2026-07-15-notifications-architecture-decisions-50a4c728.md` — why notifications address `User` rows in the first place.
- ClickUp `86ey9nzyn`; PR title21-CGT/cgt-backend#73.