---
name: universal-agent-creator
description: 创建、校验并自动安装跨平台 Agent（子智能体）。当用户说“创建一个 agent / 子智能体 / 代码审查 agent / 规划 agent / 让所有 AI IDE 都能用这个 agent / 同步 agent 配置 / 把某个角色做成 agent”时使用；覆盖 Claude Code、Qoder、Qoder CN、Codex、TRAE、TRAE CN，并自动转换 Markdown / TOML / .agent.md 格式。即使用户只提到一个 IDE，也默认安装到本机全部可用平台；TRAE 当前只支持项目级自定义 Agent，会装到项目的 .github/agents。不用于一次性提示词，也不用于技能（技能走 universal-skill-creator）。
metadata:
  short-description: Build once, delegate in every AI IDE
---

# Universal Agent Creator

Create one canonical Markdown agent, then convert and install it into every AI IDE on the machine. The bundled `scripts/agentctl.py` owns the per-platform conversion, file naming, conflict protection, backups, and freshness checks.

An **agent** is a role with its own system prompt that the main assistant can delegate to. A **skill** is a workflow the main assistant loads. If the user wants a repeatable procedure rather than a delegate, use `universal-skill-creator` instead.

## Platform outputs

| Platform | User-level | Project-level | Format |
|---|---|---|---|
| Claude Code | `~/.claude/agents/<name>.md` | `.claude/agents/<name>.md` | Markdown + YAML |
| Qoder CN | `~/.qoder-cn/agents/<name>.md` | `.qoder/agents/<name>.md` | Markdown + YAML |
| Qoder IDE | `~/.qoder/agents/<name>.md` | `.qoder/agents/<name>.md` | Markdown + YAML |
| Codex | `~/.codex/agents/<name>.toml` | `.codex/agents/<name>.toml` | TOML |
| TRAE CN / TRAE | not supported | `.github/agents/<name>.agent.md` | Markdown + YAML |

TRAE custom agents are workspace-scoped in the versions verified on this machine. Do not claim a user-level TRAE agent; install the TRAE copy into the project the user will open. The same `.github/agents` format is used by VS Code/Copilot custom agents, so that copy can be reused there.

## What makes an agent portable

- **Canonical format.** One Markdown file with YAML frontmatter: `name`, `description`, optional `tools`, optional `model`, then the system prompt as the body. The canonical copy lives at `~/.claude/agents/<name>.md` by default.
- **Name and filename match.** Lowercase hyphen-case, at most 64 characters. The installer keys every platform on this name.
- **Description is the delegation trigger.** State what the agent does, when the main agent should delegate, and the user phrases that should cause a delegation. Write it in Chinese and/or English to match the user's language. Be a little pushy, but bound it: an overbroad description steals work from the main assistant.
- **Tools are optional and platform-specific.** Omit `tools` to inherit all tools; that is the most portable choice. When specified, use a comma-separated string in the canonical file: Claude and Qoder read that form; the TRAE copy becomes a YAML list; Codex drops the field and applies its own tool policy. Tool names that exist in Claude may not exist in TRAE or Codex, so verify before relying on restrictions.
- **Model is optional and not portable.** `inherit` is the safest default for Claude/Qoder. Codex and TRAE copies omit the model, because their model catalogs differ. If a specific model is required, configure it in that platform after installation.
- **The body is the system prompt.** Put role, scope, workflow, output contract, and boundaries there. Explain why a constraint matters instead of stacking absolute MUSTs. Do not include secrets. Keep it self-contained: agents are single files, and bundled references are not portable across all platforms.
- **Avoid non-official fields.** `color`, `expertise`, `mcp_tools`, and similar invented keys are ignored or rejected. Stick to `name`, `description`, `tools`, and `model`.

## Workflow

### 1. Capture the intent

Extract from the conversation first: the role, the tasks it should own, examples of when to delegate, boundaries, and any tool or model restrictions. Then ask only what is missing:

- What should this agent be responsible for, and what should it explicitly not do?
- Which user phrases or situations should cause the main agent to delegate?
- Does it need tool restrictions, or should it inherit everything?
- User-level or project-level? Which platforms? Default to all detected platforms.

If the user wants a one-off prompt or a workflow the main agent should follow directly, stop and explain that a skill is the better fit.

### 2. Draft the canonical agent

Create it in the default canonical location unless the user wants another source:

```bash
python <this-skill-dir>/scripts/agentctl.py init <name> --description "<delegation-trigger description>"
```

Add tools or a model only when they are genuinely needed:

```bash
python <this-skill-dir>/scripts/agentctl.py init <name> \
  --description "..." \
  --tools "Read, Grep, Glob" \
  --model inherit
```

Then replace the scaffold body with:

- A short role statement.
- A `## Workflow` section with concrete steps and the expected output.
- A `## Boundaries` section naming what the agent must not do.
- Output contract or report format, if the result is structured.

### 3. Validate

```bash
python <this-skill-dir>/scripts/agentctl.py validate <agent-file>
```

Fix every error. Review warnings: a short description will undertrigger; a description over 1024 characters may be truncated; non-portable fields will be ignored; an absolute home path will break on another machine. The canonical file must have a non-empty body and no unfinished TODO placeholders.

### 4. Install everywhere

```bash
python <this-skill-dir>/scripts/agentctl.py detect
python <this-skill-dir>/scripts/agentctl.py install <agent-file> --all
```

This writes user-level Claude, Qoder CN, Qoder IDE, and Codex copies. TRAE is reported as skipped because it is project-scoped. Then install the TRAE copy into the project the user will open:

```bash
python <this-skill-dir>/scripts/agentctl.py install <agent-file> \
  --ide trae-cn,trae --scope project --project-root <project-dir> --create-missing
```

For updates, preview and then apply:

```bash
python <this-skill-dir>/scripts/agentctl.py install <agent-file> --all --update --dry-run
python <this-skill-dir>/scripts/agentctl.py install <agent-file> --all --update
python <this-skill-dir>/scripts/agentctl.py install <agent-file> \
  --ide trae-cn,trae --scope project --project-root <project-dir> --update
```

The installer:

- Converts the canonical Markdown into Claude/Qoder Markdown, Codex TOML, and TRAE `.agent.md`.
- Skips an identical destination, refuses to replace a differing one without `--update`, and backs up replaced files under `~/.universal-agent-creator/backups/<ide>/`.
- Deduplicates shared project destinations (Qoder CN/Qoder IDE, TRAE CN/TRAE).
- Treats the canonical file's own platform destination as `source` instead of rewriting it.

### 5. Verify and hand off

```bash
python <this-skill-dir>/scripts/agentctl.py list --name <name> --from <agent-file>
python <this-skill-dir>/scripts/agentctl.py list --name <name> --from <agent-file> \
  --ide trae-cn,trae --scope project --project-root <project-dir>
```

User-scope copies should be `current`; TRAE project copies should be `current` when checked in project scope. Then tell the user:

- Start a new session in Claude Code, Qoder, and Codex so they rescan agent directories.
- In TRAE, open the project and select the custom agent in the chat/subagent UI; the `.github/agents` file is workspace-scoped.
- Give 2–3 realistic delegation prompts. For Claude/Qoder, the main agent should delegate based on the description. For Codex, behavior depends on its agent/subagent support and `[agents] enabled` in `~/.codex/config.toml`; if that setting is false, report it instead of silently editing the user's config.
- Ask which platform they use most and iterate on the description if delegation is too eager or too rare.

### 6. Iterate

Edit the canonical file, validate, and re-run the user-scope and TRAE project installs with `--update`. Use `list --from` to confirm all copies are current.

If the user wants a full benchmark of agent behavior, use the IDE's own evaluation tooling or a test project. Do not install a demo agent into every IDE just to test; use a throwaway `AGENTCTL_HOME` for dry runs.

## Command reference

Resolve `<this-skill-dir>` as the directory containing this `SKILL.md`; every installed copy is self-contained. If the runtime does not expose that path, use the canonical `~/.claude/skills/universal-agent-creator` copy.

```bash
python agentctl.py detect [--json]
python agentctl.py init <name> [--dest DIR] [--description TEXT] [--tools "A, B"] [--model inherit]
python agentctl.py validate <agent-file> [--json]
python agentctl.py install <agent-file> [--all] [--ide ID[,ID]] \
  [--scope user|project] [--project-root DIR] [--create-missing] \
  [--update] [--dry-run] [--json]
python agentctl.py list [--name NAME] [--from AGENT_FILE] [--ide ID[,ID]] \
  [--scope user|project] [--project-root DIR] [--json]
```

On Windows, if `python` is not on PATH, use `py -3` instead.

## Guardrails

- Agents are system prompts with tool access. Do not create an agent that bypasses approvals, exfiltrates data, or hides its actions. Review the body and tool list before installing.
- Omit `tools` only when full inheritance is appropriate. For least privilege, specify a narrow tool list and verify it on each platform; Codex will not receive the same list.
- Use `--dry-run` before `--update`, and rely on the backup folder if a replacement looks wrong.
- Do not create `foo`, `foo-codex`, and `foo-trae` variants. One canonical agent, one name, one description.
- Do not guess a user-level TRAE agent path. TRAE custom agents are project-scoped in the verified builds; install into `.github/agents` of the project the user will open.
- If an IDE does not show the agent, check the path from `detect`, the frontmatter, the platform's agent setting, and a restart. Report the exact path instead of copying to a random location.

## Extending to another platform

Add one `Target` in `scripts/agentctl.py` with the platform's config directory, user-level agent directory (or `None` for project-only), project subdirectory, and output format. Then test with a throwaway agent: `detect` → `install --ide <new-id>` → start a new session → confirm delegation. If the platform uses the `.agent.md` convention, the existing TRAE renderer may be reusable; if it uses a different schema, add a renderer rather than forking the canonical agent.

See `references/agent-formats.md` for verified paths, fields, and platform caveats.
