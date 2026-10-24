# 权威源与三仓职责（B07）

| 仓库 | 权威内容 | 不承担 |
|---|---|---|
| K `eng-knowledge-assets` | 资产语义、批准与 scope、record/registry/INDEX、生命周期状态、退役/替代关系 | 工程实现细节、公共组件分发 |
| I `eng-asset-ai-components` | 工程实现、构建产物、测试/消费证据、实现历史与发布候选 | 资产批准语义、通用公共组件 |
| G `ai-native-basic-component` | 通用能力（skills/hooks/gates/schemas/tools）、经批准的公共分发物与来源指针 | 领域资产事实、替代 K 做批准 |

## 开发源与分发

- 领域资产先在 I 开发和证明，K 只记录“资产是什么、批准范围是什么”。
- 进入 G 的公共分发物必须来自已批准实现包，并保留 `source_record`、`release_channel`、来源 revision/artifact hash。
- 允许 G 为通用运行时做适配，但适配必须可追踪、可批准、可复验；不得用“逐字一致”替代职责约定，也不得在 G 私自增强资产语义。
- K 的批准记录是语义权威；I/G 不得只检查形式字段后自行扩大语义。发现权威冲突时先修 K，再同步 I/G。

## 版本与基线

- 历史 record 的 `5267/5277` 来源 revision 可保留，用于追溯当时批准基线；当前发布物必须声明其实际引用的规范 revision。
- 同一资产跨仓发布时，使用 `asset_id` + 不可变正文 hash + package version 固定版本，不使用浮动“最新”。
