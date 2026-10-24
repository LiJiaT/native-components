# memory/

可复用的 memory 条目模板与公共记忆。一个条目一个 Markdown 文件。

## 当前收录

| 条目 | 层级 | 作用 |
|---|---|---|
| [`asset-taxonomy.md`](asset-taxonomy.md) | 公共级 | 资产分类体系：9 领域平铺 + 2 固定项目 + 四维正交 |

领域子目录只放真实资产。synthetic 示例（EA-07/09 等）在 [`samples/synthetic/`](../samples/synthetic/)；它们不随安装器安装，也不得写入生产 memory。

## 适用

- 跨项目稳定成立的事实、约定、环境基线。
- 可被多个项目会话加载的公共背景知识。

项目私有事实放对应项目的 memory 目录，不放这里。

## 条目要求

- frontmatter 标注 `asset_id`（若由资产流程产出）、`ai_form: Memory`、来源与 `provenance_status`。
- 一条记忆只表达一个结论；写明适用前提与失效条件。
- 不粘贴原始记录、会议全文、日志；只保留提炼后的结论。
- 定期复核：前提变化即更新或删除，避免过期记忆继续被加载。

## 领域子目录

领域级条目按 [`docs/domain-taxonomy.md`](../docs/domain-taxonomy.md) 的 slug 放在对应子目录：

`architecture/`、`design/`、`verification/`、`timing/`、`dft/`、`post-sim/`、`firmware/`、`analog/`、`backend/`

项目私有条目仍放对应项目的 memory 目录，不进这里。
