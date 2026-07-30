---
metadata:
  confidence: 0.8
  created: '2026-07-30T09:42:18.962155+00:00'
  source: /teamvault-publish
  tags:
  - tenancy
  - multi-tenancy
  - rbac
  - network
  - tenant
  - membership
  - permissions
  - architecture
  - decision
  - cgt-backend
  - cgt-frontend
---

---
created: 2026-07-30T12:00:00Z
source: /teamvault-publish
confidence: 0.95
author: Israel Abebe
decision_type: decision
kingdom: title21-cgt
palace: cgt-backend
wing: tenancy
hall: architecture
room: _
tunnels:
  - 2026-07-15-notifications-architecture-decisions
tags:
  - tenancy
  - multi-tenancy
  - rbac
  - network
  - tenant
  - membership
  - permissions
---

# Tenancy: networks, tenants, memberships and per-tenant roles

## Context

ClickUp `86eyefz78`, PRs title21-CGT/cgt-backend#113 and title21-CGT/cgt-frontend#181. Real multi-tenancy
plus the follow-up that applied the product owner's rulings. Merged to `dev` and adopted on a deployed
environment via the Tenancy Setup page on 2026-07-30.

The PO answered three questions that shaped everything below:

1. Everything is managed at the **tenant** level. Nothing at the network level.
2. **Networks are not managed in the app.** Each network gets its own deployment. The network name only
   needs to be displayed.
3. A user holds **a different role in each tenant** (admin at one hospital, supervisor at another).

## The model

```
Network (exactly ONE row, the instance record)
  └── Tenant ──┬── all 33 tenant-scoped tables
               └── TenantMembership ──┬── User (isSuperAdmin: Boolean)
                                      └── Role ── RolePermission
```

One sentence per `TenantMembership` row: **this user, in this tenant, with this role**. Plus a superadmin
flag that sits above tenancy entirely.

## Decisions

1. **Network is an instance record, not a managed entity.** One deployment hosts one network, so
   `NetworkMembership`, all network CRUD, and the network selector are gone. What remains is
   `GET /api/networks/current` returning `{ id, name, metadata }`, and `NetworksService.onModuleInit`
   creating the row when the table is empty. `Tenant.networkId` stays NOT NULL, so a deployment with no
   Network row could never create its first tenant. The existing `metadata` JSON column is where
   instance-level config goes without another migration.

2. **Roles live on the membership, not the user.** `User.roleId` is dropped;
   `TenantMembership.roleId` replaces it. `@@unique([userId, tenantId])` is what makes the model work: it
   permits "admin in tenant 1, supervisor in tenant 2" while making "two roles in one tenant"
   unrepresentable. `roleId` is nullable, and **NULL means member with zero permissions there**, not
   member with default permissions.

3. **Superadmin is a flag, not a role.** `User.isSuperAdmin`, set directly. Previously platform access was
   a side effect of holding a role whose `fullAccess` was true, which meant the runtime could not tell a
   platform admin from a hospital admin. A role can only ever mean something *inside* one tenant, so
   platform access had to stop being one. The seeded `super-admin` role is retired.

4. **No per-user permission overrides.** `permissionGrants` / `permissionDenials` are dropped; access is
   purely role-based. When per-user tweaks return they land as override columns on the **membership**, so
   they can differ per tenant.

5. **Cognito is authentication only.** The app never writes Cognito groups and authorization never reads
   them, with exactly one exception: a principal with NO DB row falls back to its token group, so a fresh
   environment can be administered before the User table is populated. Per-request DB resolution also means
   a role change takes effect immediately with no re-login.

## The security invariant (the important part)

**`X-Tenant-Id` is client-controlled, so tenant permissions must never satisfy a route without a tenant
guard.**

Without this, a custom tenant role containing `users.manage` plus a spoofed header would unlock platform
user management. `PermissionsGuard` therefore decides whether a route is tenant-scoped by reflecting the
route's `__guards__` metadata for `TenantContextGuard` / `TenantParamGuard`:

| Request | Permission source |
|---|---|
| `isSuperAdmin` | everything, everywhere, short-circuits |
| route carries a tenant guard | `tenantPermissions[tenant]`, the caller's role in THAT tenant |
| anything else (global routes) | the shell baseline only, so global management is superadmin-only |

The shell baseline is deliberately tiny: `dashboard.view` + `tenants.read`. It is NOT the "undeniable"
permission set, which includes `submissions.read` / `forms.read` and would hand clinical data to every
principal.

Both `permissions.guard.spec.ts` and `test/auth.e2e-spec.ts` pin the spoofed-header case over real HTTP.

**Guard ordering consequence:** `PermissionsGuard` is global and runs BEFORE controller-level tenant
guards, so an unknown or non-member tenant is refused 403 by the permission check before the tenant guard
can return its 400. That is intentional: it does not disclose whether a tenant exists to a caller with no
access. Do not "fix" it.

**Frontend corollary:** gate each **control** by the routes it calls, not each screen by its topic. A
control hitting a global route gates on `isSuperAdmin`, **not** on `can(key)`: a tenant role may
legitimately hold `users.manage`, and gating on that would render a control whose every request 403s.

**Corrected 2026-07-30, later the same day.** This section originally listed Tenants alongside Users,
Roles, Feature Flags and Sources as a surface to gate on `isSuperAdmin`, which contradicted the
delegation rule two sections below and shipped as a bug: a tenant admin could not see Configure to
Tenants at all. **Configure to Tenants is a MIXED surface.** Tenant CRUD and the network rename are
global (superadmin); that tenant's own members panel is delegable and gates on `can('users.manage')`.
The tab now opens for `isSuperAdmin || can('users.manage')` and `TenantsSettings` gates its two halves
separately. Users, Roles, Feature Flags and Sources are unchanged: every route behind them is global.

One asymmetry falls out of delegating members. Adding a member needs a user id, which only the global
superadmin-only `GET /users` provides, so tenant admins get `POST /tenants/:tenantId/members/by-email`
instead, and the frontend must gate its `['users', …]` query on `isSuperAdmin` (not on the members
permission) or a tenant admin 403s there silently. A tenant admin can also provision a brand new account
via `POST /tenants/:tenantId/members/create`; that route is tenant-scoped while creating a **platform**
identity, so the service forces `isSuperAdmin: false` and a single membership in the URL's tenant, and
`CreateMemberDto` omits both fields so `forbidNonWhitelisted` 400s an attempt to send them. Creation is
an explicit second step after the by-email 404, never an automatic fallback: emails are globally unique,
so auto-creating on a typo would permanently squat the correct address.

## Load-bearing rules

- **Never put `tenantId` in a request DTO.** They are client-spoofable. Resolve from context via
  `@CurrentScope()` and pass it as the first positional service arg. The one deliberate exception is
  `tenancy-setup`, where choosing the target tenant is the point.
- Scoped services filter and stamp through `src/common/tenant-scope.ts`: `whereTenant(scope)` for lists,
  `tenantOwns(scope, rowTenantId)` for point lookups, `machineScope(tenantId)` for webhook ingest.
- **NULL `tenantId` means legacy** (pre-tenancy rows). The app never writes NULL scope columns. Full-access
  reads include NULL rows during adoption; regular members never see them.
- Composite uniques are tenant-prefixed (`[tenantId, mrn]`, `[tenantId, din, productCode]`), so the same
  MRN can exist in different tenants. Note the exception: `FormDefinition` is `@@unique([familyId, version])`,
  deliberately un-prefixed because familyIds are generated and never collide across tenants.
- Managing a tenant's members IS delegable: `/tenants/:tenantId/members*` carries the tenant in the URL and
  mounts `TenantParamGuard`, so it resolves against the caller's role in that tenant. Platform user
  administration is not delegable below superadmin.

## Traps this work surfaced

- **Name-only lookups across tenants.** Both seed scripts matched existing rows by name while creating them
  tenant-stamped, so another tenant's same-named row suppressed creation of this tenant's copy and left it
  with an incomplete set. `prisma/seed.ts` has no dev-only guard and runs on container boot under
  `SEED_ALL_ON_START`, so it could reach dev and staging. Any "find existing by name" in a tenant-scoped
  codebase needs the tenant in the predicate.
- **Divergent audit actors.** Eleven controllers each defined their own `actorOf`; two written during this
  work put `userId` first while nine used `email` first, quietly making `createdBy` a UUID on some routes
  and an email on others. Now one helper at `src/common/actor.ts`.
- **A pre-tenancy "users are global" assumption surviving behind a tenant guard.**
  `GET /api/equipment/assignable-users` sits on a `TenantContextGuard` controller, so it looks scoped and
  `PermissionsGuard` treats it as scoped, but the service took no scope and returned **every enabled user
  on the instance** with the raw email as a display-name fallback. It needs only `equipment.read`, which
  `USER_BASE` grants, so the basic `user` role in any tenant could enumerate every account. Fixed by
  filtering on `tenantMemberships: { some: { tenantId } }`. **Being behind a tenant guard is not the same
  as being tenant-filtered**: the guard authorizes the caller, the service still has to scope the query.
  Worth auditing any service method that takes no scope argument on a guarded controller.

## Open / known limitations

- **Scope columns are still nullable.** A follow-up flips them NOT NULL and deletes `src/tenancy-setup/`
  plus the legacy-visibility fallback, once every environment reports all-zero unassigned counts.
- **A legacy patient (tenantId NULL) is invisible to the `tenantId_mrn` key**, so opening a case for one
  before adoption mints a second, tenant-stamped patient and splits history. Documented and accepted for
  now; Tenancy Setup reports the collision on assign-all.
- **Six audit/mapping tables are still unscoped**, including `FormFieldMapping`.
- Terminology writes have no permission key: reads are public, writes are `@AuthOnly`, so any signed-in
  user can rewrite platform-wide wording.

## Related

- `2026-07-30-cgt-tenancy-deploy-and-adoption.md` for what a deploy actually requires, including the
  zero-superadmin lockout.
- `2026-07-15-notifications-architecture-decisions-50a4c728.md` is now **partly outdated** by this work.
  Its "`User` has no `tenantId`, scope it once `User.tenantId` lands" note should be read as: users relate
  to tenants through `TenantMembership`, not a column, so notification audiences should resolve through
  memberships. The `createForPermission` resolver was reworked here because it read the dropped
  `permissionGrants` / `permissionDenials` columns. Default audience is still every enabled user in every
  tenant; scoping it remains a separate ticket.