---
name: teamvault-upstream-sync
description: Pull substrate updates from the master template (`tin-io/teamvault`) into the team's space fork WITHOUT clobbering team-owned content. Use when the user says "sync upstream", "pull from upstream", "update the substrate", "what's new in tin-io/teamvault", or asks how to bring in upstream sidecar / docs / skill changes. Targeted-path checkout (USER_GUIDE Pattern A) with gray-zone customization detection, dry-run preview, and rollback path. Handles the "fork-free clone" case (no `upstream` remote configured yet) natively by prompting to add it.
---

# TeamVault Upstream Sync

Walks the user through pulling upstream substrate updates (sidecar code, docs, base skills, reference packs) into their team's space fork — without touching team-owned content (`kb/entries/`, `space.yaml`, `repos.yaml`, custom packs).

Substrate vs. team-owned vs. gray-zone, per [USER_GUIDE §Upstream sync](../../docs/USER_GUIDE.md):

| Layer | Paths | This skill |
|---|---|---|
| **Substrate (upstream owns)** | `sidecar/`, `docs/`, `.github/`, `.claude/skills/teamvault-*`, `README.md`, `SETUP_PROMPT.md`, `LICENSE` | Always pulled |
| **Reference packs (gray zone)** | `packs/{hipaa-reference,clickup,jira-linkage}/` | Pulled UNLESS team has local commits modifying them; then asks |
| **Team-owned (yours forever)** | `space.yaml`, `repos.yaml`, `kb/entries/**`, custom packs | Never touched (not in the path list) |

## Preconditions

Verify these BEFORE proceeding. Surface any failure and STOP — do not try to work around.

```bash
test -f "$PWD/space.yaml" && echo "ok: in a TeamVault space" || echo "FAIL: no space.yaml in cwd"
git -C "$PWD" status --porcelain                              # must be empty
git -C "$PWD" branch --show-current                            # capture for later
git -C "$PWD" remote -v | grep -E '^upstream\s' || echo "no upstream remote"
```

If `space.yaml` is missing: the cwd is not a TeamVault space — ask the user to `cd ~/teamvault-<their-space>` first.

If `git status --porcelain` is NOT empty: working tree is dirty. Surface the changed paths and ask the user to commit or stash before re-running this skill. Do NOT proceed — the targeted checkout below will mix uncommitted work into the sync commit.

If `git branch --show-current` is not the default branch (`main` for most forks): warn explicitly — "syncing on branch `<X>` instead of `main`; if intentional, proceed; otherwise `git checkout main` first." Do not abort; some teams sync on a release branch.

Capture the current space dir + branch + sidecar port for later steps:

```bash
SPACE_DIR="$PWD"
SPACE_NAME=$(basename "$SPACE_DIR")
CURRENT_BRANCH=$(git -C "$SPACE_DIR" branch --show-current)
PORT="${TEAMVAULT_PORT:-8100}"
```

## Flow

### 1. Decide dry-run vs. apply

Ask the user before doing anything that changes git state:

> "Dry-run first (recommended — shows upstream delta + the diff you'd commit, but stops before commit), or apply directly? [dry-run / apply — defaults dry-run]"

Capture as `DRY_RUN=1` (default) or `DRY_RUN=0`. The skill follows the same flow either way through §5; §6 (commit) is the branch point.

```bash
DRY_RUN=1  # default; override to 0 if user picks "apply"
```

For a "nervous first run" the dry-run shows exactly what would land — the user can read `git diff --staged` and either re-invoke with `apply` or `git reset HEAD -- .` to clear and walk away. No rollback needed for a dry-run since no commit is created.

### 2. Ensure `upstream` remote is configured

Many forks have it; the "fork-free clone" case (team pushed their fork to a new empty repo, severing the GitHub fork relationship) does not. Treat both identically by asking:

```bash
if ! git -C "$SPACE_DIR" remote -v | grep -qE '^upstream\s'; then
  HAS_UPSTREAM=0
else
  HAS_UPSTREAM=1
fi
```

**If `HAS_UPSTREAM=0`, ask the user:**

> "No `upstream` remote configured in this fork. I'd like to add `https://github.com/tin-io/teamvault.git` as `upstream` so we can fetch substrate updates from there. (This is git config only — read-only from upstream's perspective; nothing pushes back.) Add it? [Y/n]"

If yes:

```bash
git -C "$SPACE_DIR" remote add upstream https://github.com/tin-io/teamvault.git
git -C "$SPACE_DIR" remote -v | grep '^upstream'   # confirm
```

If the user declines: STOP. We cannot sync without knowing where "upstream" points. Suggest they re-run after deciding which repo is the canonical substrate source.

### 3. Fetch upstream and show the delta

```bash
git -C "$SPACE_DIR" fetch upstream
UPSTREAM_SHA=$(git -C "$SPACE_DIR" rev-parse --short upstream/main)
echo "upstream/main is at $UPSTREAM_SHA"

# Show commits this fork is missing, scoped to substrate paths.
SUBSTRATE_PATHS=(
  sidecar/ docs/ .github/
  .claude/skills/teamvault-setup/
  .claude/skills/teamvault-status/
  .claude/skills/teamvault-publish/
  .claude/skills/teamvault-review/
  .claude/skills/teamvault-doctor/
  README.md SETUP_PROMPT.md LICENSE
)

git -C "$SPACE_DIR" log --oneline HEAD..upstream/main -- "${SUBSTRATE_PATHS[@]}"
```

If the log output is empty, there's nothing new on substrate paths. Tell the user "no substrate updates upstream — your fork is current"; STOP (skip steps 4-9). Pack-only updates are handled in §4 — fall through to that check before declaring complete.

### 4. Gray-zone customization check (reference packs)

For each reference pack (`hipaa-reference`, `clickup`, `jira-linkage`): check whether the team has any commits modifying that path which are NOT reachable from `upstream/main`. Those are local customizations that a blind checkout would overwrite.

```bash
GRAY_ZONE_PACKS=(hipaa-reference clickup jira-linkage)
SKIP_PACKS=()

for PACK in "${GRAY_ZONE_PACKS[@]}"; do
  PACK_PATH="packs/$PACK/"
  [ ! -d "$SPACE_DIR/$PACK_PATH" ] && continue   # pack not in this fork

  # Commits on the current branch that touch this pack and are NOT on upstream/main.
  LOCAL_COMMITS=$(git -C "$SPACE_DIR" log --oneline upstream/main..HEAD -- "$PACK_PATH" | head -20)

  if [ -n "$LOCAL_COMMITS" ]; then
    echo "⚠️  packs/$PACK/ has local commits (will be overwritten by checkout):"
    echo "$LOCAL_COMMITS"
    # Ask the user; default Y = skip (safer — preserves customization).
    # If user answers Y or empty: SKIP_PACKS+=("$PACK")
    # If user answers n: include in checkout, accept overwrite
    SKIP_PACKS+=("$PACK")
  fi
done
```

**The prompt to ask per gray-zone hit:**

> "Your team has customized `packs/$PACK/` (local commits above). Pulling upstream will overwrite those changes. Skip pack sync for this pack? [Y/n — defaults Y / skip]"

Default to skip — the cost of skipping is "you don't get upstream's pack updates this round"; the cost of NOT skipping is "your custom scrubbers / agents / regex patterns silently vanish." Skip is recoverable; clobber is not (without a `git reset --hard HEAD~1`).

After the loop, derive the actual path list for §5:

```bash
CHECKOUT_PATHS=("${SUBSTRATE_PATHS[@]}")
for PACK in "${GRAY_ZONE_PACKS[@]}"; do
  if [ -d "$SPACE_DIR/packs/$PACK" ] && [[ ! " ${SKIP_PACKS[*]} " =~ " $PACK " ]]; then
    CHECKOUT_PATHS+=("packs/$PACK/")
  fi
done
```

Tell the user explicitly which packs are skipped vs. included so the upcoming `git diff --staged` is not surprising.

### 5. Targeted-path checkout

```bash
git -C "$SPACE_DIR" checkout upstream/main -- "${CHECKOUT_PATHS[@]}"
```

The checkout stages all referenced paths against the working tree. Show the staged diff for review:

```bash
git -C "$SPACE_DIR" diff --staged --stat        # summary first
git -C "$SPACE_DIR" diff --staged               # full diff
```

Tell the user: "Review the diff above. Substrate paths should all look like deliberate upstream changes; reference-pack paths (if any were included) should be reviewed extra carefully — those are the gray zone."

### 6. Commit gate

**If `DRY_RUN=1`:** STOP here. Tell the user:

> "Dry-run complete. The diff above is what `apply` mode would commit. To proceed, run this skill again and pick `apply` at step 1. To clear the staged changes now: `git -C $SPACE_DIR reset HEAD -- .` and `git -C $SPACE_DIR checkout -- .` (the latter restores files from HEAD)."

Do not run those reset commands automatically — let the user choose to clear or hold the staged state for inspection.

**If `DRY_RUN=0`:** ask the user before committing:

> "Commit this sync? Commit message will be: `chore(sync): upstream $UPSTREAM_SHA [paths: <list>]`. [Y/n]"

If user declines: roll back the staged checkout (see `## On failure → user declined commit`) and STOP.

If user confirms, build the commit. List included path roots (sidecar, docs, .github, .claude/skills/teamvault-*, plus any reference packs that weren't skipped) in the message footer for audit:

```bash
# Build a short, human-readable summary of what's included
INCLUDED_LABELS=(sidecar docs .github .claude/skills/teamvault-*)
for PACK in "${GRAY_ZONE_PACKS[@]}"; do
  if [ -d "$SPACE_DIR/packs/$PACK" ] && [[ ! " ${SKIP_PACKS[*]} " =~ " $PACK " ]]; then
    INCLUDED_LABELS+=("packs/$PACK")
  fi
done
INCLUDED_STR=$(IFS=, ; echo "${INCLUDED_LABELS[*]}")

git -C "$SPACE_DIR" commit -m "chore(sync): upstream $UPSTREAM_SHA [paths: $INCLUDED_STR]"
```

### 7. Push to origin

```bash
git -C "$SPACE_DIR" push origin "$CURRENT_BRANCH"
```

If the team's space repo has branch protection that requires a PR for any push to `main`, the direct push will fail. In that case, push a sync branch and open a PR — tell the user:

```bash
# Fallback if direct push to main is blocked:
SYNC_BRANCH="chore/upstream-sync-$UPSTREAM_SHA"
git -C "$SPACE_DIR" checkout -b "$SYNC_BRANCH"
git -C "$SPACE_DIR" push -u origin "$SYNC_BRANCH"
gh pr create --title "chore(sync): upstream $UPSTREAM_SHA" \
  --body "Pulls substrate updates from \`upstream/main\` at \`$UPSTREAM_SHA\`. Paths: $INCLUDED_STR."
```

`space.yaml::compliance: true` spaces should expect this fallback path (the same gate that turns §3-bind into a PR in `/teamvault-setup` applies here).

### 8. Kickstart the sidecar

Substrate updates likely include `sidecar/` Python — the running sidecar is still on the OLD code until the launchd process restarts:

```bash
launchctl kickstart -k "gui/$(id -u)/dev.teamvault.sidecar"
```

If the user is running the sidecar manually (no launchd plist — e.g., dev sandbox), they'll need to restart it themselves: `Ctrl-C` the running `uvicorn` and re-launch.

### 8.5. Deploy new/updated substrate skills to user-global

The targeted-path checkout brought new and updated `teamvault-*` skills into `$SPACE_DIR/.claude/skills/`, but Claude Code looks in `~/.claude/skills/` (user-global, registered via `--scope user` at original install) for slash-command discovery. Copy them over so the new skills are invocable from any project the dev is in — without this step, slash commands like `/teamvault-upstream-sync` and `/teamvault-bind-project` only resolve when the user's cwd is inside the space dir, and existing `~/.claude/skills/teamvault-*` copies stay frozen on the version they were at install time.

```bash
mkdir -p "$HOME/.claude/skills"

SUBSTRATE_SKILLS=(
  teamvault-setup teamvault-status teamvault-publish teamvault-review
  teamvault-doctor teamvault-upstream-sync teamvault-bind-project
)
DEPLOYED_GLOBAL=()

for NAME in "${SUBSTRATE_SKILLS[@]}"; do
  SRC="$SPACE_DIR/.claude/skills/$NAME"
  DST="$HOME/.claude/skills/$NAME"
  if [ -d "$SRC" ]; then
    rm -rf "$DST"
    cp -r "$SRC" "$DST"
    DEPLOYED_GLOBAL+=("$NAME")
  fi
done

echo "Deployed to ~/.claude/skills/: ${DEPLOYED_GLOBAL[*]}"
```

**Tell the user:** each substrate skill that landed in this sync has been re-copied to `~/.claude/skills/`. **Run `/quit` and relaunch Claude Code** to pick up the new + updated slash commands. The sidecar's MCP tools (`vault_search`, `vault_publish`, etc.) don't need a Claude Code restart — they were registered at `--scope user` during the original install and stay current via the sidecar's HTTP API.

**Conflict policy:** this step OVERWRITES user-global substrate skill copies without prompting. The user invoked `/teamvault-upstream-sync` explicitly to pull substrate updates; that includes the skill files. Machine-local customizations to a `teamvault-*` skill should live elsewhere (e.g., in a `teamvault-*-custom/` directory) so they aren't overwritten by routine syncs.

### 9. Post-sync verification

```bash
# Give the sidecar a few seconds to come back up after kickstart.
for i in 1 2 3 4 5 6 7 8; do
  curl -sf "http://localhost:$PORT/healthz" >/dev/null && break
  sleep 2
done

curl -s "http://localhost:$PORT/healthz" | python3 -m json.tool
```

Expect `status: ok` and the space registered. If `status` is anything else, or curl never succeeds: go to `## On failure → post-sync verification failed`.

If healthy: tell the user to run `/teamvault-doctor` for a deeper check (pull staleness, MCP registration, structural drift) — `healthz` only confirms the FastAPI app booted; doctor confirms the space and indexes look sane post-sync.

Confirm to the user:

- Upstream SHA pulled: `$UPSTREAM_SHA`
- Paths included: `$INCLUDED_STR`
- Packs skipped (preserved local customization): `${SKIP_PACKS[*]:-none}`
- Sidecar healthy on `:$PORT`
- Next step: `/teamvault-doctor` for the deep check

## On failure

- **Working tree dirty at preflight**: surface `git status` output to the user. Ask them to commit or stash, then re-run. Do NOT try to stash on their behalf — the team's local changes may be unfinished work they need to inspect.

- **`upstream` remote add declined or unreachable**: STOP at §2. The user has to either point us at a substrate source or proceed manually. `git remote add` failures (e.g., URL malformed, conflicting remote name) surface git's error directly.

- **`git fetch upstream` fails (auth / network)**: surface git's error. Common causes: no network, GitHub credential helper picking the wrong account (the multi-account-gh gotcha — see `/teamvault-setup` §1.5 for SSH workaround), or `upstream` URL typo. STOP — without a successful fetch, `upstream/main` is stale.

- **`git checkout upstream/main -- <paths>` fails**: most likely a substrate path was removed upstream (e.g., a skill was renamed) and isn't present in the current ref. Re-run §3 to see the upstream delta — if `git log` shows the rename, the user needs to manually checkout only the paths that still exist, then handle the rename separately. File as an upstream-coordination follow-up; do not improvise on the user's working tree.

- **User declined commit at §6**: roll back the staged checkout cleanly:
  ```bash
  git -C "$SPACE_DIR" reset HEAD -- .
  git -C "$SPACE_DIR" checkout -- .
  ```
  The reset un-stages; the checkout restores files from HEAD. Working tree is back where it started. Tell the user "no commit made; no changes on disk; safe to walk away." Same recovery as dry-run cleanup.

- **`git push` rejected (branch protection)**: fall back to the PR path in §7 (sync branch + `gh pr create`). Do NOT `git push --force` or bypass protections. The PR path is the right answer for `compliance: true` spaces anyway.

- **`launchctl kickstart` fails**: surface the error. Common cause: the sidecar plist isn't installed (the user is running the sidecar manually, e.g., in dev sandbox). In that case: tell them to restart their `uvicorn` process. The sync IS committed and pushed; only the running sidecar is stale.

- **Post-sync verification failed (healthz never returns ok)**: this is the rollback case. The commit is on disk + pushed; the sidecar is broken on the new code. Tail the log:
  ```bash
  tail -50 "$HOME/.teamvault/logs/sidecar.err.log"
  ```
  Common causes: a new sidecar dependency was added upstream that isn't in the venv (run `cd "$SPACE_DIR/sidecar" && .venv/bin/pip install -r requirements.txt`), or upstream changed a module path the plist references. If the user can't fix forward in <5 min, roll the sync commit back:
  ```bash
  git -C "$SPACE_DIR" reset --hard HEAD~1
  git -C "$SPACE_DIR" push --force-with-lease origin "$CURRENT_BRANCH"   # ASK before force-pushing
  launchctl kickstart -k "gui/$(id -u)/dev.teamvault.sidecar"
  ```
  **ASK the user before `--force-with-lease`** — that rewrites origin history; teammates whose sidecars already pulled the bad commit will need to reset too. For a single-dev space this is usually fine; for a multi-dev space, prefer a forward-fix commit (`git revert HEAD` + push) over the force-push.

- **No upstream commits to pull (§3 log empty AND no gray-zone packs included)**: not a failure — tell the user "your fork is already current with upstream substrate" and STOP. No commit, no push, no kickstart needed.
