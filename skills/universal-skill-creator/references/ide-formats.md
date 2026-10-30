# IDE formats and discovery notes

Verified on this Windows machine on 2026-10-22. Treat paths as conventions that can change between IDE versions; the installer centralizes them so an update only needs one edit in `scripts/skillctl.py`.

## Installed AI IDEs

| IDE | Install location | Config root | Skill root |
|---|---|---|---|
| Claude Code | CLI | `~/.claude` | `~/.claude/skills` |
| Qoder CN | `%LOCALAPPDATA%/Programs/Qoder CN` | `~/.qoder-cn` | `~/.qoder-cn/skills` |
| Qoder IDE | `%LOCALAPPDATA%/Programs/Qoder IDE` | `~/.qoder` | `~/.qoder/skills` |
| TRAE CN | `%LOCALAPPDATA%/Programs/Trae CN` | `~/.trae-cn` | `~/.trae-cn/skills` |
| TRAE | `%LOCALAPPDATA%/Programs/Trae` | `~/.trae` | `~/.trae/skills` |
| Codex | CLI / desktop | `~/.codex` | `~/.codex/skills` |
| Shared Agent Skills | cross-tool convention | `~/.agents` | `~/.agents/skills` |

`TraeCLI` shares the TRAE desktop family and uses the TRAE config root. It does not have a separate skill directory.

## Discovery behavior

### Claude Code

- Loads user-level skills from `~/.claude/skills` and project-level skills from `.claude/skills`.
- A skill is discovered by its folder plus `SKILL.md`; there is no registry file to edit.
- New skills are picked up at session start.

### Qoder (CN and IDE)

- Native user-level roots are `~/.qoder-cn/skills` and `~/.qoder/skills`.
- The desktop bundle enables `skills.loadFromAgentsDirectory`, so Qoder also loads skills from the shared `~/.agents/skills` directory.
- The migration records for this machine use `~/.qoder-cn/skills` and `~/.qoder/skills` as functional roots, with `~/.agents/skills` supplying the same skills to the agent runtime.
- A new session or a window reload refreshes the skill list.

### TRAE (CN and international)

- Native user-level roots are `~/.trae-cn/skills` and `~/.trae/skills`.
- The workbench bundle contains a default-on setting described as “Automatically load agent skills from the .agents/skills folder”, so the shared root is also read.
- Project-level support includes `.trae/skills`; the migration notes also record `.claude/skills`, `.claude/rules`, `CLAUDE.md`, and `.agents/skills` as workspace-level inputs.
- Local skills are normally directory-scanned. Marketplace-installed skills are additionally recorded in `skill-config.json`; that registry is for marketplace management, not a requirement for a plain local folder.
- If a new local skill does not appear, restart TRAE before assuming registration is needed.

### Codex

- Codex resolves skills under `$CODEX_HOME/skills`; when `CODEX_HOME` is unset, that is `~/.codex/skills`.
- The built-in skill creator ships its own `.system/skill-creator` and `.system/skill-installer` under the same root. Do not modify `.system`.
- Codex reads `name` and `description` frontmatter. It optionally uses `agents/openai.yaml` for UI metadata and invocation policy; that file is not required for the skill to work.
- Codex’s own validator is strict about unknown frontmatter keys: it allows `name`, `description`, `license`, `allowed-tools`, and `metadata`. Keep new skills to that set to avoid a Codex-specific failure.
- A new thread or restart refreshes the skill list.

### Shared `~/.agents/skills`

- This is the best fallback for any Agent Skills-compatible tool without a native root.
- On this machine it holds a physical copy of the Claude skills, not a symlink. Copies are used because Windows symlink creation may require privileges.
- Duplicate copies in `.agents` and native roots are expected. They must be identical; otherwise different IDEs can execute different instructions for the same skill name.

## Frontmatter compatibility

| Field | Claude Code | Qoder | TRAE | Codex |
|---|---|---|---|---|
| `name` | required | required | required | required |
| `description` | required | required | required | required |
| `metadata` | accepted | accepted | accepted | accepted |
| `license` | accepted | likely ignored | likely ignored | accepted |
| `allowed-tools` | Claude-only behavior | ignored | ignored | accepted but runtime-specific |
| other top-level keys | may be ignored | may be ignored | may be ignored | rejected by built-in validator |

Practical rule: use only `name`, `description`, and optionally `metadata.short-description`. If a skill needs tool restrictions, express them in the body and name the target runtime explicitly.

Name rules are shared: lowercase letters, digits, hyphens; no leading/trailing hyphen; no consecutive hyphens; at most 64 characters; folder name must match. Description limit is 1024 characters; avoid `<` and `>` because Codex rejects them.

## Project-level roots

| IDE | Project root |
|---|---|
| Claude Code | `.claude/skills` |
| Qoder | `.qoder/skills` |
| TRAE | `.trae/skills` |
| Codex | `.codex/skills` |
| Shared | `.agents/skills` |

Project installs are opt-in. The installer skips a project that has no matching IDE config unless `--create-missing` is passed, which avoids scattering empty `.trae`, `.qoder`, and `.codex` directories through unrelated repositories.

## Copy and backup model

- Canonical source: `~/.claude/skills/<name>` by default.
- Install targets: every detected user root, plus the shared root.
- Identity check: a SHA-256 tree hash over relative paths and file bytes.
- Replacement policy: identical copies are skipped; differing copies require `--update`; replaced copies are moved to `~/.universal-skill-creator/backups/<ide>/<name>-<timestamp>` before the new copy is written.
- Backups live outside skill roots so IDE scanners do not treat them as additional skills.
- `list --name <name>` reports the short hash per IDE and flags drift.

## Adding a new IDE

1. Add a `Target` in `scripts/skillctl.py` with `id`, `label`, config directory, user skill root, and project skill root.
2. Run `detect` to confirm the config directory is found.
3. Create a throwaway skill, run `install --ide <new-id>`, and start a new session in that IDE.
4. Confirm the skill appears and triggers on its description.
5. If the IDE has no native skill root but supports Agent Skills, point its user root at `~/.agents/skills` instead of inventing a path.

Do not guess a native path and silently copy into it. A wrong path creates a skill that never triggers and hides the real problem.
