# Claude Code 内部机制与模型事实（实测/源码确认）

## [1m] 后缀机制
[1m] 是客户端标记，不是发给服务端的模型名（发请求前剥掉）。作用是改写客户端上下文窗口记账：模型名含 [1m] → 窗口按 1M 记账（否则自定义模型落默认 200K）。给自定义模型加 [1m] 可把 auto-compact 触发点从 200K 提到 1M；不发 context-1m beta 头。`[claude-code:unrecognized_model]` stderr 只是"模型不在内置目录"的提示，不是错误。可用 `CLAUDE_CODE_DISABLE_1M_CONTEXT=1` 关闭。

## 模型优先级与 /model 持久化
优先级：`--model` > env.ANTHROPIC_MODEL > settings.json model 键。/model 接受任意字符串并写入 model 键，但 env 里留着 ANTHROPIC_MODEL 会压过它——**要 /model 持久化必须删 env 里的 ANTHROPIC_MODEL**。别名槽位用 ANTHROPIC_DEFAULT_OPUS/SONNET/HAIKU_MODEL；ANTHROPIC_SMALL_FAST_MODEL 已废弃。
- **本机已于 2026-10-18 删除该键**（此前 /model 长期不生效：CLI 会明说 "ANTHROPIC_MODEL is set to X — new sessions use that while it is set"，见到这句即确诊）。删键后 model 键成为单一真身；同步改了 claude-sdk-headless 的 smoke_test.py（原直接 `settings["ANTHROPIC_MODEL"]` 会 KeyError，改为读顶层 model 键）。
- **该键有三方消费者**：终端 CLI（覆盖 /model，即上条 bug）、cc-connect launch.sh（source 全局 env → 传给 bot 子进程，**静默压过 provider 的 model 字段**，实测 bot 默认模型从配置的 GLM-5.3[1m] 被 env 值改成了 GLM-5.3-Flash[1m]）、SDK 脚本。改它前先扫这三处。
- **验证默认模型别用普通 shell**：Claude Code session 的 Bash 工具继承当前进程 env（含旧 ANTHROPIC_MODEL），测出来是假的。用 `env -u ANTHROPIC_MODEL claude -p '…' --output-format json` 再看 `modelUsage` 键名。

## modelPicker 键
需 Claude Code v2.1.242+；仅 User/managed settings 生效（项目/local 写了被忽略）。options[] 每行 {model 必填, label, description}；replaceBuiltInOptions: true 隐藏内置 lineup。低版本写它报 "Unrecognized field" 而非静默忽略。判定某键某版本是否支持：对单文件二进制 `strings + grep` 键名计数即可。

## 升级后旧进程的 schema 校验坑
brew 升级是软链切换，运行中会话仍用旧二进制 schema 校验 settings.json → Edit 写新键报 "Unrecognized field"（报错≠配置错）。绕过：备份 → python json 直接改文件（保持键序） → 用新二进制 `claude -p` 验证零报错。升级等待期 /model 可能并发改写 settings，Edit 前重新 Read。

## 验证实际运行模型
`cat ~/.claude/sessions/<pid>.json` 拿 sessionId+cwd → 对应 transcript `grep -o '"model":"[^"]*"'` 统计，"Set model to" 行后即为当前模型。注意：只证明请求发往哪个模型标识，无法验证网关背后真身。

## git push 认证通道隔离
VS Code 登录的 GitHub 凭据只在 VS Code 集成终端有效（GIT_ASKPASS 注入）；agent 独立 shell 没有它，密码认证必被拒。push 授权：让用户在 VS Code 集成终端跑 `git push` 或点「同步更改」。讲 git 概念时给 P4 对照表（用户 P4 背景）。

## ark 调用参数与错误分类
- GLM-5.3-Flash 结构化 JSON 输出 `max_tokens` 起步 16000（强制思考烧预算，6000 时 ~65% 截断）；解析失败先怀疑截断
- HTTP 400 SensitiveContentDetected = 确定性拒绝，立即跳过不重试（重试 ~10 分钟/条）；Connection refused/ReadTimeout = 瞬时故障，4 次递增重试可恢复

## 技能可见性：藏出用户 / 菜单的唯一正解（2026-10-09 实测纠错）
- **frontmatter `user-invocable: false`** = 从用户 / 菜单隐藏、模型仍自动触发——"仅模型可见"组合只有这一条路，settings 层四个档位都做不到
- **settings skillOverrides `"user-invocable-only"`** = 语义恰好相反（仅用户可调用）：对模型隐藏、/ 菜单仍显示（标 user-only）。与 frontmatter 同名但**非反义**，勿混
- 档位速查：`on` 双可见 / `name-only` 模型只见名 / `user-invocable-only` 模型不可见 / `off` 双隐藏（off 也藏 Remote Control 与 SDK 列表）
- `/skills` 管理界面是档位编辑器，无条件列出全部技能，不反映隐藏效果；检验面是 `/` 补全列表，且需重启 session
- 本机已落地：9 个运维手册类 skill（automode-classifier-outage/bg-cron-patrol/cc-connect-bridge/colima-rosetta-x86-docker/docker-hotpatch-upstream-fix/launchd-watchdog/ocr-bundle-repair/transcript-replay-recovery/claude-sdk-headless）均已写 `user-invocable: false`；llm-access 按用户要求保持可见

## rules paths 作用域语义（官方 memory.md 核实）
- **无 paths 的 rules**：无条件全量加载，机械上与写进 CLAUDE.md 等价（官方原话 'mechanically identical'，/compact 后重新注入）——不要误以为是"按需触发"
- **带 paths 的 rules**：只在 Claude **Read** 匹配文件时注入
- 覆盖缺口：Edit/Write 修改已存在文件经"先 Read 才能 Edit/Write"契约间接触发（安全）；但 Write 新建文件可能不触发（无先读要求）；Bash 的 rm/mv/重定向覆盖/cp/sed -i/脚本写文件完全绕过 Read，规则从未加载
- 设计含义：「禁止写/删某路径」这类必须确定执行的约束不能只靠 paths 规则兜底，要用 **PreToolUse hook 或 settings permissions** 强制（CLAUDE.md/rules 只是建议，hook 才是强制）
- @import 的相对路径由 harness 以包含文件为锚点确定性解析；skill 文档内路径引用归 skill 作者负责（写明确相对 skill 目录路径）

<!-- 来源: session c9d7259d + 93ad8e9b + aa0466cc + a96f8e6f, cand-938606/604390/8acf3c/b45e80/4e07a3/948c8a/fb9ffb/6051a0 -->
<!-- rules paths 节来源: session 64335c1a, cand-40977d, 理由: 与用户逐层核实修正'规则按路径触发'误解，含反直觉绕过缺口 -->
