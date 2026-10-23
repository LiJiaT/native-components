# 领域目录映射

资产 schema 与规范 §3.2 使用 9 个领域。组件库中的领域级资产按以下 slug 分目录存放。

| 领域 | 目录 slug | 典型资产 |
|---|---|---|
| 架构 | `architecture` | 系统架构、模块划分、接口边界 |
| 设计 | `design` | RTL 设计约束、coding style、可综合性 |
| 验证 | `verification` | DV 方法学、testbench、覆盖率策略 |
| 时序 | `timing` | STA、clock/reset、CDC |
| DFT | `dft` | scan / MBIST / boundary scan、repair |
| 后仿 | `post-sim` | 后仿环境、SDF、功耗/噪声后仿 |
| Firmware | `firmware` | 固件接口、启动流程、寄存器序列 |
| 模拟 | `analog` | 模拟/混合信号设计、PVT |
| 后端 | `backend` | 综合、布局布线、物理验证 |

## 落位规则

- 领域级 Memory → `memory/<slug>/`
- 领域级 Rule → `rules/<slug>/`
- 领域级 Skill / Workflow / Prompt 仍按类型目录存放，用 frontmatter 的 `domains` 标注领域，不强制建领域子目录。
- 领域是资产归属，不是独立运行时；安装时仍按 AI 形态落到项目 `.claude/` 或用户级 `~/.claude/` 的有效载入点。
- 项目私有资产放项目 memory / rules，不进本库的领域目录。

## 维护

新增领域时，同步更新：

1. 规范 §3.2 的领域枚举；
2. `assetize` 技能 `scripts/validate.py` 的 `DOMAINS` 常量与 `references/asset-schema.md`；
3. 本映射表；
4. `memory/`、`rules/` 下对应的领域目录。
