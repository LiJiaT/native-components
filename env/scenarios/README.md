# 场景登记（Scenario Registry）

跨 session 的长期工作线在这里登记。目的：**用户提到某条工作线时，Claude 自动加载其当前状态，无需用户说"帮我恢复上下文"**。

## 结构

```
scenarios/
  README.md
  <场景名>/
    scenario.json    # 机器可读登记：name / triggers / state / auto_history
    STATE.md         # 当前状态（~1 屏，持续更新）
    HISTORY.md       # 追加式时间线（决策 / 事故 / 里程碑）
```

`scenario.json` 是 hook 的**唯一数据源**——新增场景只需加目录 + json，无需改 hook。

## 触发机制（两层并存）

1. **常驻规则**：`~/.claude/CLAUDE.md` 的「长期场景」节列出登记表，指示 Claude 提到触发词时先读对应 `STATE.md`。
2. **确定性注入**：`~/.claude/hooks/scenario-inject.sh`（UserPromptSubmit hook）读用户输入，命中 `scenario.json` 的 `triggers` 就把该场景 `STATE.md` 注入**当轮**上下文；未命中或任何异常 → 静默退出。

两层分工：**hook 保证确定性，规则作兜底**（hook 静默失败时仍能工作）。反之，hook 的 triggers 走机械子串匹配、判断不了歧义，所以宁缺毋滥；规则层的模型能分辨歧义，可以列得更宽。

## 新增一个场景

1. `mkdir -p ~/.claude/scenarios/<name>`
2. 写 `scenario.json`：`{"name":"…","triggers":["…"],"state":"STATE.md","auto_history":false}`
3. 写 `STATE.md`（当前状态）与 `HISTORY.md`（时间线）
4. 在 `~/.claude/CLAUDE.md` 的「长期场景」表加一行
5. `git -C ~/.claude add -A && git commit`

**triggers 选词**：小写子串匹配（大小写不敏感）。要够独特，避免误触发——太泛的词（如单独一个「网关」，会命中"ark 网关"等其他上下文）宁缺毋滥；歧义词留给规则层由模型判断。

## 维护

- **本期手动**：`STATE.md` 持续更新、`HISTORY.md` 追加。
- **预留自动接口**：`scenario.json` 的 `auto_history`（默认 `false`）。二期计划接入 SessionEnd 蒸馏管线——worker 判定 session 归属场景后自动追加 `HISTORY.md` 条目。**本期不实现。**

## 状态

- 2026-10-19 建立，试点场景：`telegram`。
