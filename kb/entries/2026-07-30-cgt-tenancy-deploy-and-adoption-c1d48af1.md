---
metadata:
  confidence: 0.8
  created: '2026-07-30T09:43:14.630256+00:00'
  source: /teamvault-publish
  tags:
  - tenancy
  - multi-tenancy
  - deployment
  - migration
  - rbac
  - superadmin
  - runbook
  - gotcha
  - cgt-backend
---

---
created: 2026-07-30T12:15:00Z
source: /teamvault-publish
confidence: 0.95
author: Israel Abebe
decision_type: pattern
kingdom: title21-cgt
palace: cgt-backend
wing: tenancy
hall: operations
room: _
tunnels:
  - 2026-07-30-cgt-tenancy-networks-tenants-memberships
tags:
  - tenancy
  - deployment
  - migration
  - superadmin
  - runbook
  - gotcha
---

# Deploying tenancy: what is automatic, what is manual, and how to lock yourself out

## Why this exists

The tenancy migrations are fully automatic, which makes it easy to assume the whole rollout is. It is not.
An environment can come up with **zero superadmins**, and because every global management screen is
superadmin-only, there is then no in-app way back. This is the runbook that was actually followed for the
`dev` deploy on 2026-07-30.

See `2026-07-30-cgt-tenancy-networks-tenants-memberships-bf0df0dc.md` for the model itself.

## What happens by itself

The container `CMD` is `prisma migrate deploy && node dist/src/main.js`, so pushing to `dev` or `staging`
builds the image, forces a new ECS deployment, and the new task applies migrations before the API starts.
Nothing in the GitHub workflow runs migrations; it is the image entrypoint.

Then two boot-time services run with no intervention:

- `RbacSeedService` re-seeds the system roles and **deletes the now-retired `super-admin` role row**, since
  it is no longer in `SEEDED_SYSTEM_ROLE_SLUGS`. It also logs a loud warning if zero superadmins exist.
- `NetworksService.onModuleInit` creates the single instance `Network` row if the table is empty.

## The lockout, and why the fix expires

The migration backfills the new flag from the **`super-admin` slug only**:

```sql
UPDATE "User" u SET "isSuperAdmin" = true
FROM "Role" r WHERE r."id" = u."roleId" AND r."slug" = 'super-admin';
```

Users who held the `admin` role also had full access before (the runtime could not distinguish the two), so
they **lose platform-wide access** on deploy. They keep admin rights inside their own tenants via the
membership backfill. That part is intended and belongs in deploy notes.

The failure mode is an environment where **nobody** held the `super-admin` slug. It migrates to zero
superadmins, and Tenancy Setup is itself a global screen, so there is no way in.

**The timing trap:** `RbacSeedService` deletes the `super-admin` role row at boot, moments after the
migration runs. So fixing this by assigning someone that role only works **before** deploying. After boot
the role no longer exists to assign.

### Check before deploying

```sql
SELECT u.email, r.slug FROM "User" u LEFT JOIN "Role" r ON r.id = u."roleId";
```

If nobody has `super-admin`, do one of these first:

1. Assign the `super-admin` role to an operator account (only works pre-deploy), or
2. Set `RBAC_BOOTSTRAP_ADMINS` to an operator email in the ECS task definition. This is break-glass and now
   applies to **DB-backed** users too, not just principals with no DB row, which is what makes it a real
   recovery path rather than a fresh-environment-only bootstrap.

Post-deploy the only remedy is SQL: `UPDATE "User" SET "isSuperAdmin" = true WHERE email = '...'`.

Setting `RBAC_BOOTSTRAP_ADMINS` on every non-production environment regardless is cheap insurance.

## The instance name is write-once

`APP_INSTANCE_NAME` is read **only when the `Network` table is empty**, and all network write endpoints are
deleted. Once a row exists, that env var is ignored forever and the top bar shows whatever name is stored.
Renaming later is a SQL edit:

```sql
UPDATE "Network" SET name = 'CGT Dev'
WHERE id = (SELECT id FROM "Network" ORDER BY "createdAt" ASC LIMIT 1);
```

Check `SELECT id, name, "createdAt" FROM "Network" ORDER BY "createdAt";` before deploying. Legacy
environments may hold more than one row (networks used to be manageable); `GET /networks/current` picks the
oldest deterministically and Tenancy Setup reports `networkCount` as a sanity signal. Because the frontend
no longer filters tenants by network, every tenant appears under that one label regardless.

## The manual pass, per environment

Existing environments get **zero memberships** from the migration (the conversion step only has network
memberships to convert, and there are none on an environment that predates them). Until this pass is done,
every non-superadmin can sign in and see the shell but no tenant data, and all existing clinical data sits
in NULL-tenant limbo visible only to superadmins.

As a superadmin:

1. Configure to Tenants: create the tenant if none exists.
2. Run the Cognito user import first if some users have no DB row. The next step enumerates **DB users
   only**, so importing afterwards means running it twice.
3. Configure to Tenancy Setup: pick the tenant and a **default role**, then apply. This stamps all NULL
   scope columns, makes every user a member, and fills role-less memberships. Idempotent, so re-running
   after the import is safe.
4. Re-elevate anyone who needs global admin.

The default role matters: `apply()` bulk-creates memberships, and a NULL-`roleId` membership grants **zero**
permissions, so an assign-all without a role would leave every non-superadmin locked out of tenant data.

Success looks like Tenancy Setup reporting all unassigned counts zero, `networkCount` of 1, and
`superadminCount` above 0. That all-zero state is also the removal criterion for deleting the module.

## Also worth knowing

- **The e2e admin account needs both** `isSuperAdmin` and a membership with a role, or the scheduled suite
  fails on the first post-deploy run for reasons that look like UI regressions.
- Migrations from other branches interleave by timestamp, so merging `dev` into a long-lived branch can
  apply an older-dated migration after a newer one. `migrate deploy` handles this fine (it applies whatever
  is unapplied, in folder order), but do the merge before deploying so CI runs against the union.
- No production environment exists yet. The tenancy migrations do heavy DDL (full-table UPDATEs,
  non-concurrent unique index builds, validating FKs on `Patient` / `FormSubmission` / `Transplant`) inside
  Prisma's single transaction per file. Harmless on seeded tables, worth a `NOT VALID` + validate-later
  convention before the first production deploy. Neither repo has migration linting today.