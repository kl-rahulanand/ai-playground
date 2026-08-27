# Section 9 — Claude Code foundation

## What we configured

- **`CLAUDE.md`** (project memory) — Sentinel's purpose, structure, build/test
  commands, coding conventions, safety boundaries, and definition of done. Claude
  Code loads it automatically at the start of a session in this repo.
- **`.claude/settings.json`** — project settings: a permission allowlist for the
  `uv` commands we actually use, a deny rule for reading `.env`, and an `env`
  default of `SENTINEL_MODEL=claude-haiku-4-5`.
- **`.claude/commands/analyze-incident.md`** — a reusable slash command
  `/analyze-incident <name>` that runs the validated analysis and reports the
  outcome without overstating it.

## The reusable command

```
/analyze-incident inc-205
```
It checks the incident exists, runs `sentinel.structured_analysis`, and reports
ACCEPTED/REJECTED with the typed failure or the (honestly-stated) conclusion.
Because it's a file in `.claude/commands/`, it's versioned with the repo and
shared with anyone who clones it.

## Clean session vs continued session

- **Clean session** (`claude` fresh, or after `/clear`): no prior conversation.
  Claude starts from `CLAUDE.md` + settings only. Reproducible — the same starting
  context every time. Best for a well-specified task.
- **Continued session** (`claude --continue` / `--resume`): the previous
  conversation's context is restored. Claude "remembers" what you did — useful for
  multi-step work, but the accumulated context can also carry stale assumptions.

Rule of thumb: start clean for a new, self-contained task; continue when you're
resuming the exact thread you left. (Contrast with API "conversation history" —
that's you resending messages; a Claude Code session is the CLI managing that for
you.)

## Inspecting which instructions/settings were loaded

- `/memory` — shows the `CLAUDE.md` files in effect (project + user + enterprise).
- `/context` — shows what's currently in the context window.
- `claude --debug` — verbose startup logging, including config resolution.
- Settings precedence (highest first): enterprise managed → command-line args →
  `.claude/settings.local.json` → `.claude/settings.json` (project) → user
  `~/.claude/settings.json`. A project setting overrides your user default; an
  enterprise policy overrides the project.

## Why `CLAUDE.md` guides behaviour but is NOT a security boundary

`CLAUDE.md` is *instructions in the prompt*. It strongly shapes what Claude does,
but:
- It is advisory text, not an enforcement mechanism. A cleverly-worded request,
  a prompt injection in a file Claude reads, or simply a conflicting instruction
  can lead Claude to act against it.
- It cannot *prevent* an action. Only real controls do that: the permission
  system in `settings.json` (allow/deny/ask), hooks that block commands, file
  permissions, and sandboxing.
- Therefore: put "please don't" guidance in `CLAUDE.md`, but put "must not" in
  `permissions.deny` and hooks. In Sentinel, "never commit secrets" lives in
  `CLAUDE.md` **and** is enforced by `.gitignore` + a `deny` rule on reading
  `.env` — belt and suspenders.

This mirrors the whole week's thesis: instructions influence a model; the
application (and its real controls) enforce the boundary.
