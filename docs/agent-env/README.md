# agent-env/ — Claude Code 与 agent 环境的事实笔记

来源：本机 `~/.claude/memory/`（快照仓 `claude-code-env/projects/-Users-lidaonian/memory/`），2026-10-27 迁移进本仓库。
迁移依据：`遗留事项-仓库改名.md` §4.2 的「应先迁入远端仓库」清单。

## 收录

| 文件 | 主题 | 本地原文件是否保留 |
|---|---|---|
| `claude-code-internals.md` | `[1m]` 后缀、模型优先级链、modelPicker schema、升级 schema 坑、git push 认证隔离、ark 参数与错误分类 | 是（带「已迁至」标注） |
| `claude-code-hook-pitfalls.md` | 写 hook 的四个实测坑：stdin 被吃、`grep -c` 零匹配污染、SessionEnd 1.5s、自指入队 | 是 |
| `dom-verification.md` | 生成式 HTML 控件的 DOM 验证方法：stub 事件不冒泡、重置值是语义值 | 是 |
| `work-log-deferred.md` | work-log skill 的延期决策与模板 | 是 |
| `model-eval-rtl-asyncfifo.md` | 异步 FIFO RTL 生成对比框架与首轮结论 | 是 |
| `openclaw-migration-map.md` | OpenClaw / Copilot / Claude Code 三工具资产迁移映射 | 是 |

## 这里不是什么

- **不是 approved asset record**：这些笔记没有走 `assetize` → owner 批准 → `native-assets` 登记流程，
  所以不进 `registry.json`，也不受 `tools/install.py` 管理。
- **不是 `memory/<domain>/`**：那 9 个领域（analog / architecture / backend / design / dft / firmware / post-sim / timing / verification）
  是芯片工程域；这 6 篇是 agent 工具链自身的环境知识，放进去会污染领域分类。

## 后续处置

若其中某篇要成为可分发组件，按正常流程走：`skills/assetize` 产出提案 → owner 批准 → `native-assets` 登记 →
`skills/asset-ai-ize` 生成实现包。届时从本目录移走并在此处留指针。
