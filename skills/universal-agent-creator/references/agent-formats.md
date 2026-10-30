# Agent formats and discovery notes

Verified on this Windows machine on 2026-10-22. Agent formats differ more than skill formats, so the installer converts a canonical Markdown agent into each platform's own representation.

## Platform matrix

| Platform | User-level | Project-level | Output |
|---|---|---|---|
| Claude Code | `~/.claude/agents/<name>.md` | `.claude/agents/<name>.md` | Markdown |
| Qoder CN | `~/.qoder-cn/agents/<name>.md` | `.qoder/agents/<name>.md` | Markdown |
| Qoder IDE | `~/.qoder/agents/<name>.md` | `.qoder/agents/<name>.md` | Markdown |
| Codex | `~/.codex/agents/<name>.toml` | `.codex/agents/<name>.toml` | TOML |
| TRAE CN | not supported | `.github/agents/<name>.agent.md` | Markdown |
| TRAE | not supported | `.github/agents/<name>.agent.md` | Markdown |

## Claude Code

- One Markdown file per agent. Frontmatter fields used by the runtime: `name`, `description`, `tools` (optional), `model` (optional).
- `tools` is a comma-separated string such as `Read, Grep, Glob`. Omit it to inherit the session's tools.
- `model` accepts aliases such as `sonnet`, `opus`, `haiku`, `fable`, or `inherit`. `inherit` is the safest cross-platform default.
- The main agent delegates based on the description, so the description must say when to use the agent, not just what it is.
- User-level and project-level agents are both loaded. Project agents are useful for repo-specific reviewers.
- New agents are picked up at the start of a new session.

## Qoder (CN and IDE)

- Qoder reads local agents in the same Markdown shape as Claude: frontmatter `name`, `description`, optional `model`; the body is the agent prompt. Existing user agents on this machine use `model: inherit`.
- User-level roots are `~/.qoder-cn/agents` and `~/.qoder/agents`.
- The Qoder settings UI lists local agents and reports a config directory; the agent list refreshes on a new session or window reload.
- The project-level `.qoder/agents` path follows the workspace configuration convention. Treat it as a convention to verify in the installed Qoder version rather than a documented universal path.
- Qoder-specific agent model IDs differ from Claude. `inherit` avoids hard-coding a model that Qoder cannot resolve; if a specific model is required, choose it in Qoder's UI.
- Qoder's tool names and tool-policy syntax are not guaranteed to match Claude. Omit `tools` unless the restriction is essential, and verify the agent still has the tools it needs.
- Qoder's runtime also references Qoder-specific fields such as `descriptionZh`, `argumentHint`, `allowedTools`, and `disallowedTools`. These are not emitted by the portable generator; if Qoder-specific tool restrictions or UI hints matter, set them in Qoder after installation.

## Codex

- Codex agent definitions are TOML files under `$CODEX_HOME/agents`; the default is `~/.codex/agents`. The project-level convention is `.codex/agents`.
- The existing working files on this machine use:
  ```toml
  name = "..."
  description = "..."
  nickname_candidates = ["..."]
  developer_instructions = "...\n..."
  ```
  The generator emits exactly these fields. `developer_instructions` is a TOML basic string with escaped newlines and quotes.
- Codex's binary exposes an `AgentRoleToml` shape with `description`, `config_file`, and `nickname_candidates`; the existing files also use `name` and an inline `developer_instructions`. Mimic the existing working files rather than inventing fields.
- Codex's `[agents] enabled = true` setting in `~/.codex/config.toml` controls agent support. If it is false, report it; do not silently edit the user's config.
- Codex TOML does not carry the canonical `tools` list. Codex applies its own tool policy. If least privilege matters, configure it in Codex rather than assuming the Claude list transfers.
- Codex TOML does not carry the canonical `model`. Choose the model in Codex if needed.
- A new thread or restart refreshes the agent list.

## TRAE (CN and international)

- TRAE custom agents are workspace-scoped in the verified builds. The file lives at `.github/agents/<name>.agent.md`; any `.md` under `.github/agents` is classified as an agent, and `.agent.md` is the explicit suffix.
- There is no verified user-level TRAE agent directory. Do not install to `~/.trae-cn/agents` or `~/.trae/agents` and claim it works.
- The custom-agent model in the workbench exposes these fields: `name`, `description`, `tools`, `model`, `argumentHint`, `handoffs`, `target`, `infer`, and the body as instructions. The generator emits `name`, `description`, and optional `tools`; it omits `model` to avoid an invalid model alias.
- `tools` is emitted as a YAML list for TRAE, because the custom-mode parser expects a structured tool list. Claude/Qoder copies use a comma-separated string instead.
- TRAE tool names are not guaranteed to match Claude tool names. Verify the agent's tools after opening the project.
- The same `.github/agents` convention is used by VS Code/Copilot custom agents; a TRAE project copy can be reused there.
- Open the project in TRAE and select the custom agent in the chat/subagent UI. Restart or reload the window if it does not appear.

## Shared `~/.agents` directory

`~/.agents/skills` is a verified cross-tool skills location for Qoder and TRAE. There is no equivalent verified `~/.agents/agents` loader for agent definitions. Do not use a shared agents directory as a substitute for native roots; install to Claude/Qoder/Codex/TRAE paths explicitly.

## Conversion rules

| Canonical field | Claude/Qoder Markdown | Codex TOML | TRAE `.agent.md` |
|---|---|---|---|
| `name` | `name` | `name` + `nickname_candidates` | `name` |
| `description` | `description` | `description` | `description` |
| `tools` | comma-separated string | omitted | YAML list |
| `model` | passed through | omitted | omitted |
| body | system prompt | `developer_instructions` | system prompt |

The canonical source is a Markdown file with YAML frontmatter. The installer normalizes quoting and line endings, so generated copies may not be byte-identical to the source even when they are semantically current.

## Validation rules

- Name: lowercase letters, digits, hyphens; at most 64 characters; must match the filename (with `.agent` stripped if present).
- Description: required; the main agent uses it for delegation. Short descriptions undertrigger; descriptions over 1024 characters may be truncated by some runtimes.
- Body: required; it is the system prompt. Avoid unfinished TODO placeholders and secrets.
- Frontmatter: `name`, `description`, `tools`, `model` only. `color`, `expertise`, `mcp_tools`, and similar fields are not portable.
- Tools: a comma-separated string or a YAML list is accepted in the canonical file; the installer normalizes them for each platform. A canonical Claude/Qoder file should use the comma-separated form.
- Absolute home paths in the body are warned about because they break on another machine.

## Adding a platform

1. Add a `Target` in `scripts/agentctl.py` with its config directory, user-level directory (or `None` for project-only), project subdirectory, and format.
2. If the format is not Markdown or the Codex TOML shape, add a renderer.
3. Test with a throwaway `AGENTCTL_HOME`, install to the new target, and confirm the platform lists and delegates to the agent in a new session.
4. Do not guess a user-level path for a platform that only documents project-level agents. An inert file that looks installed is worse than an explicit "project-only" status.
