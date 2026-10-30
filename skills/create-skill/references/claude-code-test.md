# Claude Code 真实触发协议（三个 create 技能共用）

> 本文件是 `create-skill` / `create-hook` / `create-agent` 的共用验收协议，**只此一份**。
> 目的：证明"新建的组件真的被 Claude Code 用上了"，而不是"文件存在"。

## 0. 前提

| 项 | 要求 |
|---|---|
| 可执行文件 | `claude.cmd`（Windows；`claude.ps1` 会被 PowerShell ExecutionPolicy 拒绝） |
| 版本记录 | 跑前执行 `claude.cmd --version`，把版本写进 `result.md` |
| 隔离 | 沙箱放 `reports/<task>/sandbox/<case>/`，**不碰**用户级配置目录 |
| 成本 | 单次约 60 秒 / 0.15 美元；每个 case 先算预算再跑 |

## 1. 沙箱形状

```text
reports/<task>/sandbox/
├── c1-skill/.claude/skills/<probe>/...        # 项目级技能
├── c2-hook/.claude/{settings.json,hooks/<probe>/...}
└── c3-agent/.claude/agents/<probe>.md

reports/<task>/test-evidence/<case>/{stream.jsonl,stderr.log,files/,hashes.txt,result.md}
```

每个 case 是独立目录，并作为 `claude -p` 的工作目录——项目级 `.claude` 会被加载。**用户级 `~/.claude` 仍会生效**（实测用户级 hooks 同样触发），所以判据必须锚定到本组件自身的输出特征，不能只看事件类型。

## 2. 统一命令形态

```bash
claude.cmd -p "<prompt>" \
  --output-format stream-json --verbose \
  --permission-mode acceptEdits \
  > test-evidence/<case>/stream.jsonl 2> test-evidence/<case>/stderr.log
echo "exit=$?"
```

- `stream-json` 是唯一可判定的证据源：里面有 `tool_use`、`subagent`、`session_id`。
- `--permission-mode acceptEdits` 只为沙箱内的文件写入授权；需要跑脚本时再加 `--allowedTools "Read,Write,Edit,Bash(python:*)"`，并在 `result.md` 记下实际参数。
- 跑完把 `stream.jsonl` 的 `session_id`、耗时、费用写进 `result.md`。

## 3. 三个用例

### C1 · 技能被调用

1. 用 `create-skill` 生成样例技能（例：`probe-file-naming`，职责是给目标目录输出命名违规清单）。
2. 跑 `validate_component.py --type skill` 必须 exit 0。
3. 沙箱里跑：

   ```bash
   claude.cmd -p "用 probe-file-naming 技能检查 src 目录的文件命名" --output-format stream-json --verbose --permission-mode acceptEdits
   ```

4. **通过判据**：`stream.jsonl` 中出现该技能的调用记录，且技能约定的产物文件真实生成、内容符合契约。

### C2 · Hook 被触发

1. 用 `create-hook` 生成最小 hook（SessionStart 向 `test-evidence/c2-hook/marker.txt` 追加一行）。
2. 把 `settings.example.json` 复制为沙箱 `.claude/settings.json`，命令路径改成沙箱内绝对路径。
3. 在沙箱目录跑一次 `claude -p`。
4. **通过判据**：`marker.txt` 出现该行；`stream.jsonl` 里有本 hook 的 `hook_response` 且其输出含本 hook 的特征串；该事件的 `session_id` 与 marker 一致。
   ⚠️ 不能只看 `hook_started`/`hook_response` 个数：用户级 hooks 也在此事件上触发，必须用 hook 自身输出（如 additionalContext 文本）区分。

### C3 · Agent 被派发

1. 用 `create-agent` 生成最小 agent（`probe-ok`，只回 `OK`）。
2. 放进沙箱 `.claude/agents/probe-ok.md`。
3. 跑：

   ```bash
   claude.cmd -p "把这件事委派给 probe-ok 子代理：只回复 OK" --output-format stream-json --verbose
   ```

4. **通过判据**：`stream.jsonl` 出现该 `subagent_type` 的派发记录，返回内容含 `OK`。

## 4. 失败回退（三级，不许直接判"通过"）

| 现象 | 一级回退 | 二级回退 | 仍失败 |
|---|---|---|---|
| 项目级 skill 未加载 | 用 `--settings` 指沙箱 settings | 在 prompt 里用 `/技能名` 显式调用 | 记录"项目级 skill 加载受限"到 `regression.md`，**不算通过** |
| 项目级 hooks 未加载 | 用 `--settings` 合并 hooks 配置 | 用 `CLAUDE_CONFIG_DIR` 指向沙箱并把鉴权字段只读复制过去 | 同上，记录限制 |
| 项目级 agents 未加载 | 用 `--agents <json>` 注入同等定义 | 收窄样例（只回文本，不调工具） | 同上 |
| 工具权限被拒 | 确认 `--permission-mode acceptEdits` 生效 | 收窄样例（只读不写） | 记录并重设计样例 |

## 5. 证据要求

每个 case 的 `test-evidence/<case>/` 必须包含：

| 文件 | 内容 |
|---|---|
| `stream.jsonl` | 完整流式输出（不得裁剪） |
| `stderr.log` | 告警原文（如 `unrecognized_model`） |
| `files/` | 被生成的产物副本 |
| `hashes.txt` | `sha256sum` 形式，覆盖 stream、产物、组件文件 |
| `result.md` | 用例、命令、exit code、判据、结论（通过/失败+原因） |

## 6. 收尾

- 删除沙箱里的可执行脚本与 `settings.json`，只保留 `test-evidence/`；
- 在 `regression.md` 里登记每个 case 的判据与结论，失败项写明回退层级；
- 任何"看起来应该能触发"但没有 stream 证据的，一律按未通过处理。
