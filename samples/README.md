# 样例与测试资产

`synthetic/` 下是**仅用于流程验证**的构造资产，不是真实工程结论：

- 不进入 `registry.json` 的 active 组件，不随安装器安装。
- 生产安装/分发默认拒绝 `provenance_status: synthetic`（`gates/gate.py` 与 `validate_build.py --release` 都会阻断）。
- 引用时必须保留 frontmatter 中的 `provenance_status: synthetic` 与 `provenance_note`。

领域目录（`rules/<domain>/`、`memory/<domain>/`）只放真实资产；测试样例统一放本目录，避免被误当作领域资产加载。
