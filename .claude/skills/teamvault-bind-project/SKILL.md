---
name: teamvault-bind-project
description: Bind the current project repo to an already-installed TeamVault space. Use when TeamVault is ALREADY installed on this machine (sidecar running, MCP registered) and the user wants to add a 2nd, 3rd, Nth project repo to the team space. Appends to repos.yaml, writes the project-side CLAUDE.md block, and (optionally) deploys the pr-* workflow skills. Does NOT install the sidecar, clone the space, or register MCP — for a clean install, use /teamvault-setup instead.
---

# TeamVault Bind Project

Add the project repo the user's current shell is in to an existing TeamVault space. Assumes TeamVault is already installed locally — this skill is purpose-built for the "I'm starting work in another project today, bind it to the team space" case where re-running `/teamvault-setup` would crash on the existing space clone.

## Preconditions

Verify these BEFORE proceeding. Surface any failure and STOP — do not try to work around. If TeamVault is NOT installed yet, point the user at `/teamvault-setup` instead.

```bash
# Sidecar is running and reports healthy
PORT="${TEAMVAULT_PORT:-8100}"
curl -sf "http://localhost:$PORT/healthz" >/dev/null \
  || { echo "ERROR: TeamVault sidecar not responding on :$PORT. Run /teamvault-doctor or /teamvault-setup first."; exit 1; }

# MCP endpoint is registered with Claude Code (--scope user from initial install)
claude mcp list 2>/dev/null | grep -q teamvault \
  || { echo "ERROR: 'teamvault' MCP not registered. Run /teamvault-setup."; exit 1; }

# Current directory is a git repo
git -C "$PWD" rev-parse --git-dir >/dev/null 2>&1 \
  || { echo "ERROR: $PWD is not a git repo. cd into the project you want to bind."; exit 1; }

# Current directory is NOT the team space dir. Writing CLAUDE.md into the
# space dir creates a dirty file the sidecar's git_sync halts on — empirically
# observed during the 2026-06-25 Shalom demo where /teamvault-bind-project
# was invoked with cwd == $SPACE_DIR and the resulting CLAUDE.md tripped the
# "local changes block sync" halt. Bind operates on PROJECT repos, never on
# the team space itself.
if [ -f "$PWD/space.yaml" ]; then
  echo "ERROR: $PWD looks like a TeamVault space directory (space.yaml present)."
  echo "  /teamvault-bind-project operates on PROJECT repos, not the team space."
  echo "  cd into the project repo you want to bind (e.g. ~/Projects/<my-app>),"
  echo "  then re-run this skill."
  exit 1
fi
```

If any check fails, **do not proceed** — `/teamvault-doctor` and `/teamvault-setup` are the right next steps.

## Flow

### 1. Discover `$SPACE_DIR`

Find where the running sidecar's space lives. Try the launchd plist first (authoritative — it's what the running sidecar process actually sees); fall back to a `~/teamvault-*` directory scan only if the plist lookup returns nothing.

**Preferred — read the running sidecar's plist:**

```bash
PLIST="$HOME/Library/LaunchAgents/dev.teamvault.sidecar.plist"
SPACE_DIR=""

if [ -f "$PLIST" ]; then
  # Use plutil for a structured read — robust to whitespace differences and
  # safer than grepping XML. Falls through to grep-based extraction if
  # plutil is unavailable or the key isn't present.
  SPACE_DIR=$(plutil -extract EnvironmentVariables.TEAMVAULT_SPACE_ROOT raw -o - "$PLIST" 2>/dev/null || true)

  # Fallback: pull the value out of the XML directly. The plist shape from
  # /teamvault-setup §5 has a <key>TEAMVAULT_SPACE_ROOT</key> followed by a
  # <string>...</string> on the next line.
  if [ -z "$SPACE_DIR" ]; then
    SPACE_DIR=$(awk '
      /<key>TEAMVAULT_SPACE_ROOT<\/key>/ { getline; gsub(/.*<string>|<\/string>.*/, ""); print; exit }
    ' "$PLIST")
  fi
fi
```

**Fallback — scan `~/teamvault-*`** (only if the plist lookup yielded nothing — e.g. the user installed before the plist carried `TEAMVAULT_SPACE_ROOT`, or hand-installed):

```bash
if [ -z "$SPACE_DIR" ]; then
  CANDIDATES=()
  for d in "$HOME"/teamvault-*; do
    [ -d "$d" ] && [ -f "$d/space.yaml" ] && CANDIDATES+=("$d")
  done

  if [ ${#CANDIDATES[@]} -eq 1 ]; then
    SPACE_DIR="${CANDIDATES[0]}"
  elif [ ${#CANDIDATES[@]} -gt 1 ]; then
    echo "Multiple TeamVault spaces found under \$HOME:"
    printf '  %s\n' "${CANDIDATES[@]}"
    echo "ERROR: ambiguous. Set TEAMVAULT_SPACE_ROOT in the environment, or fix the plist, and re-run."
    exit 1
  fi
fi
```

**Error if neither path produced a value:**

```bash
if [ -z "$SPACE_DIR" ] || [ ! -d "$SPACE_DIR" ]; then
  echo "ERROR: could not locate TeamVault space dir. Checked plist + ~/teamvault-*."
  echo "  - Confirm /teamvault-setup completed successfully."
  echo "  - Or run /teamvault-doctor to diagnose."
  exit 1
fi
```

Surface what was discovered:

```bash
SPACE_NAME=$(basename "$SPACE_DIR")
echo "Bound space: $SPACE_NAME at $SPACE_DIR"
```

### 2. Detect the current project remote

```bash
PROJECT_REMOTE=$(git -C "$PWD" remote get-url origin 2>/dev/null) \
  || { echo "ERROR: $PWD has no 'origin' remote. Add one or cd into the right repo."; exit 1; }

echo "Project to bind: $PROJECT_REMOTE"
```

### 3. De-dup check against `repos.yaml`

`repos.yaml` is a YAML list of `{remote, workspace}` items; may be empty. If `$PROJECT_REMOTE` already appears, surface a friendly already-bound message and **skip step 4** — but proceed to step 5 (CLAUDE.md block can still be re-written idempotently, which is useful if the previous bind missed it).

```bash
REPOS_YAML="$SPACE_DIR/repos.yaml"
ALREADY_BOUND=$(python3 -c "
import sys, yaml, pathlib
p = pathlib.Path('$REPOS_YAML')
if not p.exists():
    print('no')
    sys.exit(0)
items = yaml.safe_load(p.read_text()) or []
remotes = [(i or {}).get('remote') for i in items]
print('yes' if '$PROJECT_REMOTE' in remotes else 'no')
")

if [ "$ALREADY_BOUND" = "yes" ]; then
  echo ""
  echo "Heads up: $PROJECT_REMOTE is already bound to space '$SPACE_NAME'."
  echo "Current bindings in repos.yaml:"
  python3 -c "
import yaml, pathlib
items = yaml.safe_load(pathlib.Path('$REPOS_YAML').read_text()) or []
for i in items:
    print(f\"  - {(i or {}).get('remote', '?')}  (workspace={(i or {}).get('workspace', 'default')})\")
"
  echo ""
  echo "Run vault_status to see runtime state. Skipping the repos.yaml append; will still re-write the CLAUDE.md block (idempotent)."
  SKIP_REPOS_APPEND=1
fi
```

### 4. Append to `repos.yaml` and push (or PR-gate under compliance)

Skip this entire section if `$SKIP_REPOS_APPEND=1` from §3.

```bash
if [ -z "$SKIP_REPOS_APPEND" ]; then
  cat >> "$REPOS_YAML" <<EOF
- remote: $PROJECT_REMOTE
  workspace: default
EOF

  # Validate it still parses.
  python3 -c "import yaml; yaml.safe_load(open('$REPOS_YAML')) or []" \
    || { echo "ERROR: repos.yaml is malformed after append; abort."; exit 1; }
fi
```

**Compliance branching.** If `space.yaml::compliance: true`, the space requires a PR for any `repos.yaml` change. Otherwise direct push is fine. Read the flag and branch:

```bash
COMPLIANCE=$(python3 -c "
import yaml
d = yaml.safe_load(open('$SPACE_DIR/space.yaml')) or {}
print('yes' if d.get('compliance') else 'no')
")

if [ -z "$SKIP_REPOS_APPEND" ]; then
  cd "$SPACE_DIR"

  if [ "$COMPLIANCE" = "yes" ]; then
    BRANCH="bind/$(echo "$PROJECT_REMOTE" | shasum | cut -c1-8)"
    git checkout -b "$BRANCH"
    git add repos.yaml
    git commit -m "bind: $PROJECT_REMOTE"
    git push -u origin "$BRANCH"
    gh pr create --title "bind: $PROJECT_REMOTE" \
                 --body "Adds $PROJECT_REMOTE to repos.yaml. (compliance: PR-gated bind from /teamvault-bind-project)"
    echo ""
    echo "Compliance space: opened a PR for the bind. Bind takes effect after merge + next pull-loop tick (~60s)."
  else
    git add repos.yaml
    git commit -m "bind: $PROJECT_REMOTE"
    git push
    echo ""
    echo "Bind pushed to space '$SPACE_NAME'. Will be picked up by every dev's sidecar on the next pull-loop tick (~60s)."
  fi
fi
```

### 5. Write the project-side `CLAUDE.md` block

Idempotent — re-running on an already-bound project just replaces the block in place.

```bash
"$SPACE_DIR/sidecar/.venv/bin/python" -m sidecar.scripts.write_claude_md_block "$PWD"
```

Expected output is one of:

- `teamvault-block created in /path/to/project/CLAUDE.md` — new file
- `teamvault-block replaced in /path/to/project/CLAUDE.md` — existing block updated in place
- `teamvault-block appended in /path/to/project/CLAUDE.md` — added to existing CLAUDE.md without markers

The block is **static** — it never enumerates the team's `knowledge_topics`. The agent learns them at runtime by calling `vault_packs()`. That way the project CLAUDE.md doesn't drift when the space adds or removes packs.

### 6. Offer the user-global CLAUDE.md hint (opt-in, default NO)

A lightweight global hint covers the case where the dev does related work in an *unbound* project (script, experiment, note) — the agent still knows TeamVault exists and can call `vault_search`. Opt-in so we don't append to a curated `~/.claude/CLAUDE.md` without asking.

**Ask the user:**

> "Also add a lightweight TeamVault hint to your `~/.claude/CLAUDE.md` so the agent knows about TeamVault even in unbound projects? Defaults NO. [y/N]"

If yes, invoke the global-mode writer:

```bash
"$SPACE_DIR/sidecar/.venv/bin/python" -m sidecar.scripts.write_claude_md_block --global
```

Same idempotent semantics — re-runs replace in place rather than duplicate. If the user answered no, skip silently; mention they can re-run this skill later if they change their mind.

> **Note:** the `--global` flag is being added in parallel to this skill landing. If the writer errors with "unknown argument `--global`", surface the version mismatch and tell the user to pull the space dir or update the sidecar before re-running this step. The bind itself (§4) is unaffected.

### 7. Deploy the `pr-*` workflow skills into the project (opt-in, default YES)

Mirrors `/teamvault-setup` §7.5. The `pr-push`, `pr-review`, `pr-fix`, `pr-pipeline` skills need to live INSIDE the bound project so they fire when working there — not just inside the space repo. We commit them to the project repo so teammates who pull the project get them too, without needing TeamVault installed themselves.

Detect what the space ships:

```bash
PROJECT_DIR="$PWD"
AVAILABLE=$(ls -d "$SPACE_DIR/.claude/skills/pr-"*/ 2>/dev/null | xargs -n1 basename | tr '\n' ' ')
```

If `$AVAILABLE` is empty (this space's fork stripped the pr-* skills), surface that and SKIP this step.

Otherwise, **ask the user** (default YES — matches setup §7.5):

> "Deploy TeamVault's PR workflow skills (`$AVAILABLE`) into this project? Copies into `<project>/.claude/skills/` and commits to project git (does NOT push). You can delete later via `rm -rf .claude/skills/pr-*`. [Y/n]"

If yes, for each skill in `$AVAILABLE`:

1. If `<project>/.claude/skills/<name>/` already exists, **ask the user** whether to overwrite. Default: skip (preserves project-side customizations).
2. Otherwise copy:

```bash
mkdir -p "$PROJECT_DIR/.claude/skills"
cp -r "$SPACE_DIR/.claude/skills/$NAME" "$PROJECT_DIR/.claude/skills/$NAME"
```

After all copies, commit to the project repo. Stage **only** the deployed paths — never `git add .`:

```bash
cd "$PROJECT_DIR"
for NAME in "${DEPLOYED[@]}"; do
    git add ".claude/skills/$NAME"
done
git commit -m "deploy teamvault pr-workflow skills: ${DEPLOYED[*]}"
```

**Do NOT auto-push.** The user pushes when ready (per their standard no-push-without-approval rule).

If the user answered no: skip silently. Mention they can re-run this skill or manually `cp -r "$SPACE_DIR/.claude/skills/pr-*" "$PWD/.claude/skills/"` later.

### 8. Confirmation summary

Print a single block summarizing what was done. Be explicit about what was and wasn't touched so the user can audit.

```
Bound: $PROJECT_REMOTE → space '$SPACE_NAME'
  repos.yaml:       <appended + pushed | PR opened | already bound — skipped>
  CLAUDE.md block:  <created | replaced | appended> in $PWD/CLAUDE.md
  Global hint:      <added to ~/.claude/CLAUDE.md | skipped (user opted out)>
  pr-* skills:      <deployed: pr-push, pr-review, ... committed locally | skipped (user opted out) | not in fork>

NO Claude Code restart needed — the teamvault MCP endpoint was registered
globally (--scope user) during the initial /teamvault-setup, so vault_search,
vault_publish, and vault_status continue to work in this and every project
without restarting.

The repos.yaml change propagates to every teammate's sidecar on the next pull-
loop tick (~60s after their sidecar fetches).
```

## On failure

- **Sidecar not running** (preconditions fail): point user at `/teamvault-doctor` first; do not try to start the sidecar from this skill. `/teamvault-doctor` is the right diagnostic + remediation surface.
- **MCP not registered**: the initial install was incomplete — surface and recommend `/teamvault-setup` (which registers MCP at `--scope user`). Re-running setup is safe for the MCP-add step alone, but its earlier clone step will collide with the existing space dir; the user can run `claude mcp add ...` manually using the snippet from setup §6.
- **`repos.yaml` malformed after append**: surface the parse error; restore from git (`git -C "$SPACE_DIR" checkout -- repos.yaml`) and ask the user to inspect manually before re-running.
- **`gh pr create` fails (compliance branch)**: branch + commit + push already succeeded, so the change is safe on the remote. Surface the gh error and the branch name so the user can open the PR via the GitHub UI.
- **`write_claude_md_block` errors with `--global` unknown argument**: the user's space sidecar predates that flag. Bind itself succeeded; have them pull the space (`git -C "$SPACE_DIR" pull`) and re-run only step 6.
- **Project-repo commit fails in §7** (e.g. dirty working tree, hooks reject): the copy already happened on disk. Surface the git error; the user can stash unrelated changes, then re-stage just `.claude/skills/pr-*` and commit manually.

## Sandbox mode (for testing this skill during development)

If `$TEAMVAULT_DEV_SANDBOX` is set, point `SPACE_DIR` at it directly and skip the plist-discovery branch in §1. Run the sidecar manually on a non-default port via `uvicorn sidecar.app:app --port 18100`; export `TEAMVAULT_PORT=18100` so the healthz check in preconditions targets the right URL. Skip §7's commit if the sandbox project repo isn't on a branch you want to dirty.
