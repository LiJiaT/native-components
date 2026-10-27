---
name: dom-verification
description: 生成式 HTML 交互控件 DOM 级验证——stub dispatchEvent 不冒泡会假阴性（直连容器派发并显式 target）、select/range 重置值可能是语义值、验证脚本固化进仓库不放 /tmp
metadata: 
  node_type: memory
  type: project
  originSessionId: c1bf0a34-ab30-4ee1-9935-7fb3a4581c44
  modified: 2026-10-08T14:29:23.283Z
---

# 生成式 HTML 交互控件的 DOM 级验证

对生成的单文件 HTML（jinja 模板渲染）做全部交互控件（过滤/排序/分页/搜索/重置）自动化验证时：

1. **stub 事件冒泡坑**：stub 里对 chip 元素 dispatchEvent 的事件若不冒泡，容器级事件监听器根本收不到，直连监听的控件却"生效"——假阴性/假阳性混杂。修正：直接对容器派发事件并显式指定 `target`
2. **重置值语义**：select/range 的重置值可能是语义值（如 `'all'`）不是哨兵 `'__all'`
3. **验证标准**：每个过滤值点击后计数差异均非零合理；排序/分页/搜索/重置全部走通，与独立计算的期望对比
4. **验证脚本固化进仓库**：放 /tmp 会被系统清理删掉——按代理建议固化进仓库（verify_ui 工具），下次渲染零回归验证直接复用

<!-- 来源: session a96f8e6f, cand-f07253, 理由: UI 审计发现三个真 bug + stub 冒泡坑与 /tmp 丢失坑均为实测教训，任何生成式 HTML 验收可复用 -->
