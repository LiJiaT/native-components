# 资产消费流程（A01）

适用范围：项目或领域需要选用已入库资产时。当前只有 9 条记录，先用人工流程；重复筛选成本明显后再增加只读查询脚本，不先建 RAG 或自主推荐。

## 流程

1. **检索**：从 K 的 `INDEX.md` / `registry.json` 找候选；记录 `asset_id`、`title`、`layer`、`domains`、`projects`、`status`、`release_channel`。
2. **适用性判断**：核对 `provenance_status`、`provenance_note`、来源与目标项目/领域是否匹配；`synthetic` 只能用于测试；`deprecated/withdrawn` 不得新用。
3. **版本固定**：引用 `asset_id` + record 的不可变正文 hash（`content_sha256`）+ 发布包 `package_version`。不用“最新版”这类浮动引用。
4. **安装/引用**：使用已批准实现包的 `install.md` 指定范围；项目级资产只进入该项目，领域/公共级按声明共享。
5. **消费验收**：在消费项目留下“触发方式、输入、预期、实际结果、失败处理”证据；不能只用文件存在或 hash 相等证明业务可用。
6. **反馈**：发现不适配、过期或语义错误，写反馈单并进入 `flows/self-evolution` 的处置流程；不要自动修改已批准资产。

## 边界

- 本流程不自动决定资产价值、不自动批准、不自动外发。
- 多项目/多运行时共享时，先登记消费清单（项目、版本、owner、证据）；出现多个使用方后再建统一台账。
- 资产退出、替代或合并时，转到 `flows/asset-lifecycle/README.md`。
