"""Write or update the TeamVault block in a project repo's CLAUDE.md.

Idempotent. Three behaviors:

- File missing: create CLAUDE.md with just the block.
- Markers present: replace the existing block in place (re-bind safe).
- Markers absent: append the block at the end of CLAUDE.md.

The block is intentionally STATIC — it never enumerates `knowledge_topics`
(those come from `vault_packs()` at runtime). Same block content for every
space.

Source: PLAN-2026-06-16-pack-knowledge-topics-and-query-log.md::Part 4.

Two modes:

- Project-local (default): writes the full `teamvault-block` to
  `{project_dir}/CLAUDE.md`. Used by `/teamvault-setup` §7 and
  `/teamvault-bind-project` when a project is bound to a space.
- User-global (`--global`): writes the shorter `teamvault-global-hint`
  block to `~/.claude/CLAUDE.md` so unbound projects still get a
  defensive "if vault_status confirms a sidecar, consult the KB" nudge.
  The two block kinds use DIFFERENT marker tags and coexist safely on
  the same CLAUDE.md.

Usage
-----
    python -m sidecar.scripts.write_claude_md_block [project_dir]
    python -m sidecar.scripts.write_claude_md_block --global

`project_dir` defaults to the current working directory. Positional
arguments are ignored in `--global` mode.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import NamedTuple


PROJECT_BLOCK = """<!-- BEGIN teamvault-block -->
## TeamVault knowledge base

This project is bound to a TeamVault space. The space's enabled packs declare
the knowledge domains the team has accumulated prior art on.

- At the start of substantive work, call `vault_packs()` to see the covered
  domains.
- Before finalizing any design decision that touches a covered domain, call
  `vault_search(query, purpose=...)` — the `purpose` says what you're trying
  to decide.
- After applying or rejecting the results, call `vault_cite(query_id,
  paths_used, note)`. `paths_used=[]` is valid and records "we searched,
  nothing was useful." Always cite when you searched before a substantive
  decision.
- After completing substantive work — closing a ticket, landing a fix,
  capturing a decision, finishing a discovery session — call `vault_publish`
  to record the decision / finding / pattern. The KB compounds from what
  gets published; if every agent reads and never writes, the KB stays empty.
  Default to publishing unless the work is genuinely trivial (typo fix,
  version bump, dependency-only update).
- For domain questions outside any enabled pack, demand-side rule applies:
  ask the KB whenever you'd ask a senior teammate.
<!-- END teamvault-block -->"""

GLOBAL_BLOCK = """<!-- BEGIN teamvault-global-hint -->
## TeamVault knowledge base (if available)

If `vault_status` confirms a TeamVault sidecar is up, call `vault_packs()` to
see covered domains. For substantive work touching a covered domain, call
`vault_search(query, purpose=...)` even if you're not in a bound project —
team knowledge can be relevant to one-off scripts, experiments, and notes too.

The full per-project guidance lives in the bound project's CLAUDE.md.
<!-- END teamvault-global-hint -->"""

# DOTALL: span newlines. Non-greedy: stop at the FIRST close marker so
# duplicate (malformed) blocks downstream are left alone.
_PROJECT_MARKER_RE = re.compile(
    r"<!-- BEGIN teamvault-block -->.*?<!-- END teamvault-block -->",
    re.DOTALL,
)
_GLOBAL_MARKER_RE = re.compile(
    r"<!-- BEGIN teamvault-global-hint -->.*?<!-- END teamvault-global-hint -->",
    re.DOTALL,
)


class BlockSpec(NamedTuple):
    """Bundle of (label, block text, marker regex) for a CLAUDE.md block.

    `label` is the short name used in status messages
    (e.g. "teamvault-block", "teamvault-global-hint").
    """

    label: str
    text: str
    marker_re: re.Pattern[str]


PROJECT_SPEC = BlockSpec("teamvault-block", PROJECT_BLOCK, _PROJECT_MARKER_RE)
GLOBAL_SPEC = BlockSpec("teamvault-global-hint", GLOBAL_BLOCK, _GLOBAL_MARKER_RE)


def _write_spec(target: Path, spec: BlockSpec) -> str:
    """Write or update `spec` at `target`. Returns the status verb.

    Creates parent directories if missing (mkdir -p semantics) — needed
    for `--global` mode when `~/.claude/` doesn't exist yet.

    Returns "created" | "replaced" | "appended".
    """
    target.parent.mkdir(parents=True, exist_ok=True)

    if not target.exists():
        target.write_text(spec.text + "\n")
        return "created"

    text = target.read_text()
    if spec.marker_re.search(text):
        target.write_text(spec.marker_re.sub(spec.text, text))
        return "replaced"

    # Markers absent — append, preserving a single blank-line separator.
    if text.endswith("\n\n"):
        sep = ""
    elif text.endswith("\n"):
        sep = "\n"
    else:
        sep = "\n\n"
    target.write_text(text + sep + spec.text + "\n")
    return "appended"


def write_block(project_dir: Path) -> str:
    """Write or update the project-local block in `{project_dir}/CLAUDE.md`.

    Returns "created" | "replaced" | "appended".
    """
    return _write_spec(project_dir / "CLAUDE.md", PROJECT_SPEC)


def write_global_block(home: Path | None = None) -> str:
    """Write or update the global hint in `~/.claude/CLAUDE.md`.

    `home` defaults to `$HOME`; injectable for tests.

    Returns "created" | "replaced" | "appended".
    """
    base = home if home is not None else Path(os.path.expanduser("~"))
    return _write_spec(base / ".claude" / "CLAUDE.md", GLOBAL_SPEC)


def main(argv: list[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]

    if "--global" in args:
        # Positional args are ignored in global mode — target is fixed.
        status = write_global_block()
        target = Path(os.path.expanduser("~")) / ".claude" / "CLAUDE.md"
        print(f"{GLOBAL_SPEC.label} {status} in {target}")
        return 0

    project = Path(args[0]) if args else Path.cwd()
    if not project.exists():
        print(f"ERROR: directory does not exist: {project}", file=sys.stderr)
        return 2
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2
    status = write_block(project)
    print(f"{PROJECT_SPEC.label} {status} in {project / 'CLAUDE.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
