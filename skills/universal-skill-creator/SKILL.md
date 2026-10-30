---
name: universal-skill-creator
description: 创建、更新并自动安装跨 IDE 的 Agent Skill。当用户说“创建技能 / 做一个 skill / 把这个流程做成技能 / 让所有 AI IDE 都能用 / 同步技能 / 改完技能后更新所有 IDE”时使用；覆盖 Claude Code、Qoder、Qoder CN、TRAE、TRAE CN、Codex，以及读取 ~/.agents/skills 的工具。即使用户只提到一个 IDE，也默认安装到本机全部已安装 IDE。不用于游戏/角色扮演里的“技能”或不会复用的一次性任务。
metadata:
  short-description: Build once, run in every AI IDE
---

# Universal Skill Creator

A portable skill factory: write one skill folder, validate it, and install it into every AI IDE on this machine. The bundled `scripts/skillctl.py` owns the IDE-specific paths, copy safety, drift detection, and backups, so the same folder works in Claude Code, Qoder, TRAE, Codex, and any tool that follows the Agent Skills convention.

This is the cross-IDE evolution of `skill-creator`. Keep its core discipline — capture intent, write a lean trigger-first skill, test realistic prompts, iterate — but make installation a single command instead of a manual copy per IDE.

## What makes a skill portable

- **Frontmatter stays minimal.** `name` and `description` are required everywhere. `metadata.short-description` is a harmless optional extra. Other fields such as `allowed-tools` or `license` are tolerated by some IDEs but ignored by others; only use them when the skill genuinely depends on them, and state the dependency in the body.
- **The description is the entire auto-trigger.** Put the what and the when there, with concrete user phrases in Chinese and English. Keep it under 1024 characters, avoid angle brackets (Codex rejects them), and be a little pushy: if the skill would help, say so explicitly. All “when to use” guidance belongs in the description, not buried in the body.
- **The name is the folder.** Use lowercase hyphen-case, at most 64 characters, and keep the folder name identical. That is what every loader keys on.
- **Scripts must be cross-platform.** Prefer Python 3 standard library; resolve bundled files from `__file__`; never hardcode a home directory; handle Windows paths. Avoid Bash-only or macOS-only commands unless the skill is explicitly OS-specific.
- **One body, progressive disclosure.** Keep `SKILL.md` under about 500 lines. Put schemas, long procedures, and variant-specific detail in `references/` and read them only when needed. Use `scripts/` for deterministic or repeated operations, and `assets/` for files the output needs.
- **No per-IDE forks.** If an IDE truly needs different instructions, add a reference file and route to it from the body. Do not create four near-identical skills with different names; that guarantees drift and duplicate triggers.
- **No secrets.** Never embed API keys, tokens, passwords, or private URLs. Read them from environment variables at runtime.

## Workflow

### 1. Capture the intent

Mine the conversation first: the steps already performed, tools used, corrections the user made, input/output formats, and any examples. Then ask only the questions whose answers change the skill:

- What should it enable the agent to do, and what is the output contract?
- Which user phrases or situations should trigger it?
- Does it need scripts, references, or assets?
- User-level (all projects) or project-level (this repo only)?
- Which IDEs? Default to every detected IDE.

If the request is a one-off task, say so and skip skill creation. Do not package a workflow the user will never repeat.

### 2. Design the skill

Choose the name and write the description first; if you cannot state when the skill should trigger, the design is not ready. Pick the smallest structure that works:

- A single `SKILL.md` for a self-contained workflow.
- `scripts/` when the same deterministic operation appears repeatedly.
- `references/` when the model needs schemas, API rules, or long domain notes.
- `assets/` when the output needs templates, fonts, or starter files.

Decide the evaluation surface. Objectively verifiable outputs (file transforms, extraction, code generation) deserve 2–3 realistic test prompts. Subjective outputs (tone, design) need human review instead. Do not block installation on a full benchmark; a quick sanity run is enough to ship, and the update path is cheap.

### 3. Draft the skill

Create the canonical source in `~/.claude/skills/<name>` unless the user wants another source location. If the host IDE sandboxes writes outside the workspace, draft under `<workspace>/.skill-staging/<name>` and install from there; request approval for the IDE roots instead of weakening the sandbox. Scaffold it:

```bash
python <this-skill-dir>/scripts/skillctl.py init <name> --description "<trigger-first description>"
```

Then replace the scaffold body with:

- A short purpose statement.
- A `## Workflow` section with concrete, ordered actions and the expected output at each step.
- Only the constraints that prevent a real failure or ambiguity.
- Examples only when they change behavior; skip generic advice the model already knows.

Explain why a step matters instead of stacking absolute MUSTs. A future model should be able to generalize from the reasoning, not just obey a script.

### 4. Validate

```bash
python <this-skill-dir>/scripts/skillctl.py validate <skill-dir>
```

Fix every error. Review warnings: a short description will undertrigger; a non-portable frontmatter field will be silently ignored by some IDEs; an absolute home path will break on another machine. The validator rejects missing fields, name/folder mismatch, oversized or angle-bracket descriptions, empty bodies, and unfinished TODO placeholders.

### 5. Install everywhere

```bash
python <this-skill-dir>/scripts/skillctl.py detect
python <this-skill-dir>/scripts/skillctl.py install <skill-dir> --all
```

For an update:

```bash
python <this-skill-dir>/scripts/skillctl.py install <skill-dir> --all --update --dry-run
python <this-skill-dir>/scripts/skillctl.py install <skill-dir> --all --update
```

The installer:

- Skips a destination that is already byte-identical.
- Refuses to replace a differing destination unless `--update` is passed.
- Backs up every replaced copy under `~/.universal-skill-creator/backups/<ide>/` before moving it.
- Copies atomically through a temporary folder, restoring the backup if the copy fails.
- Treats the source root as `source` instead of copying a folder onto itself.

Use `--scope project --project-root <dir>` for a repository-local install. By default it only touches IDEs that already have a config directory in that project; add `--create-missing` if the user wants new ones.

### 6. Verify and hand off

```bash
python <this-skill-dir>/scripts/skillctl.py list --name <name>
```

Every expected IDE should show `present` with the same hash. `DRIFT` means one copy is stale; re-run the install from the canonical copy. Then tell the user:

- The skill folder is the registration; there is no separate toggle.
- Start a new session in each IDE so it rescans skill roots. Some IDEs may need a window reload or restart.
- Give 2–3 realistic prompts that should trigger the skill, and ask them to try it in the IDE they use most. Offer to adjust the description or body based on what happens.

### 7. Iterate

Edit the canonical copy, validate again, and run `install --all --update`. Use `list --name` to confirm all copies moved together.

If the user wants rigorous evaluation or description optimization, use Claude Code’s `skill-creator` when it is installed — it has the subagent benchmark and description loop. Do not duplicate that machinery here; this skill’s job is portable authoring and installation. If the skill undertriggers, sharpen the description with more specific situations and phrases. If it overtriggers, add explicit exclusions.

## Installation matrix

The script detects these roots automatically; this table is a sanity check, not a manual to-do list.

| IDE | User-level | Project-level |
|---|---|---|
| Claude Code | `~/.claude/skills` | `.claude/skills` |
| Qoder CN | `~/.qoder-cn/skills` | `.qoder/skills` |
| Qoder IDE | `~/.qoder/skills` | `.qoder/skills` |
| TRAE CN | `~/.trae-cn/skills` | `.trae/skills` |
| TRAE | `~/.trae/skills` | `.trae/skills` |
| Codex | `~/.codex/skills` | `.codex/skills` |
| Shared Agent Skills | `~/.agents/skills` | `.agents/skills` |

Notes:

- Qoder and TRAE load `~/.agents/skills` when their “load from agents directory” setting is enabled (the default). Native roots are still installed because versions and settings differ.
- Codex uses `$CODEX_HOME/skills`; the script assumes `~/.codex/skills` when the variable is unset.
- Detection is based on the IDE config directory existing. `--include-missing` forces all known user roots, including ones not detected.
- Duplicate copies across shared and native roots are intentional. Keep them identical; the installer’s hash check reports drift.

## Command reference

Resolve `<this-skill-dir>` as the directory containing this `SKILL.md`; every installed copy is self-contained, so any IDE's copy can run the installer. If the runtime does not expose that path, run `detect` from the canonical `~/.claude/skills/universal-skill-creator` copy.

```bash
python skillctl.py detect [--json]
python skillctl.py init <name> [--dest DIR] [--description TEXT]
python skillctl.py validate <skill-dir> [--json]
python skillctl.py install <skill-dir> [--all] [--ide ID[,ID]] \
  [--scope user|project] [--project-root DIR] [--create-missing] \
  [--include-missing] [--update] [--dry-run] [--json]
python skillctl.py list [--name NAME] [--ide ID[,ID]] \
  [--scope user|project] [--project-root DIR] [--json]
```

On Windows, if `python` is not on PATH, use `py -3` instead.

## Guardrails

- Review scripts before installing a skill that will be copied into every IDE. Do not install code that deletes files, exfiltrates data, or calls untrusted services without the user’s explicit approval.
- Preserve user edits: use `--dry-run` before `--update`, and rely on the backup folder if something looks wrong.
- Keep one canonical folder per skill. Do not create `foo`, `foo-trae`, and `foo-codex`; that is how trigger collisions and version drift start.
- If an IDE does not show the skill, diagnose in this order: the path reported by `detect`, the frontmatter, the IDE’s skill setting, then a restart. Report the exact path and error instead of copying to a guessed location.
- Skills are instructions, not elevated permissions. Do not use this skill to bypass an IDE’s approval or sandbox settings.

## Extending to a new IDE

Add one `Target` entry in `scripts/skillctl.py` with the IDE’s config directory, user-level skill root, and project-level skill root. Then verify with a real skill: `detect` → `install --ide <new-id>` → start a new session → confirm the skill appears. If the IDE supports Agent Skills but has no native root, install to `~/.agents/skills` and note that as the supported path.

See `references/ide-formats.md` for verified discovery behavior and frontmatter compatibility.
