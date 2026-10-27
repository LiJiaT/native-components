---
user-invocable: false
name: ocr-bundle-repair
description: 从 OCR 生成的文本 bundle（===FILE===BEGIN/END 定界符拼接多文件）拆包并修复 OCR 损伤、以静态+运行验证闭环交付时使用。触发场景：拿到 extract.py + 多文件 bundle 需要拆包、拆包后发现文件行数虚高或内容错乱、修复 OCR 引入的 YAML 缩进塌陷/JS 弯引号/Python 缩进丢失/下划线丢失/整行吞失、对修复后的代码做 py_compile/yaml/node 语法验证、用户提到"拆包 bundle"、"OCR 修复"、"定界符变体"、"修复转写文件"。
---

# ocr-bundle-repair — OCR bundle 拆包与损伤修复

## 1. 拆包：先读定界符约定

- 拆包前先读 bundle 自带的 `extract.py` 与 Guide，确认定界符约定
- **警惕五等号变体**（`=====FILE=====BEGIN`）：extract.py 用 `find()` 找不到变体时返回 **-1**，会把后续内容整段吞进上一文件——产出行数虚高的坏件（实测 577 行实为 119 行真身 + 吞并的 yaml 段）
- 写兼容多定界符的重新拆包脚本，以 Guide 中的锚点行数**逐文件核对**

## 2. 五类 OCR 损伤各有修法

| 损伤类型 | 修法 |
|---|---|
| **a. YAML 缩进塌陷** | 不要盲加缩进（会把子键抬成幻影域）。用"按键名定位的结构感知修复"：解析后数域数/子键层级，与预期对比定位掉级行。注意 section 名剥冒号后比较、`if indent==0` 跳过顶格子键等自造 bug；字节层面排查静默失效（如 legacy_map 恒为 null 是比较字符串写错） |
| **b. JS 弯引号/全角标点** | 写字符级状态机：只在字符串外替换弯引号与全角标点，字符串内的中文标点不动。配合"抽内联 JS→替换 jinja 占位→node --check"验证闭环，用二分定位第一个语法坏前缀（括号不均衡常源于上方） |
| **c. Python 缩进丢失** | py_compile 查不出的语义级错误（如 `it.update(enriched)` 掉出评分循环）要按调用点风格判断整体 +4 恢复，逐处核语义 |
| **d. 下划线丢失**（hash_url→_hash_url） | 若 Guide 有验收数据证明原程序跑过，NameError 只能是 OCR 吞的，直接按命名约定补 |
| **e. 整行吞失**（label 行、函数头 viewDelta） | 从 Guide/文档找显示名或状态枚举补齐 |

## 3. 四层验证闭环

1. `py_compile` 逐文件
2. yaml 安全加载比对结构计数（域数/子键层级）
3. `node --check` + `--help`
4. 离线 mock 冒烟：stub 网络层喂 canned 响应跑通 main 全流程，验证 dry-run/落盘/键契约/分层

## 4. 零代码改动的端点切换

原程序全靠环境变量配置（BASE_URL/MODEL/API_KEY）+ 写死路径后缀时，用 runner 脚本 import 时打补丁 + 注入环境变量，保持源码保真度。

<!-- 来源: session a96f8e6f, cand-927d5d, 理由: 整套可复用 OCR bundle 修复流程（拆包陷阱/五类损伤/四层验证），多次踩坑后收敛成稳定打法 -->
