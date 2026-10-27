---
name: llm-access
description: 通过火山引擎方舟（Volcano Ark）Agent Plan 端点稳定调用 LLM API，支持 Anthropic 与 OpenAI 两种协议、流式输出，内置实测可用的模型清单（GLM-5.3、MiniMax-M3、Kimi-K3、DeepSeek 等）和带 --help 的能力探索 CLI。凡涉及发起 LLM/大模型 API 调用、测试或对比模型、查可用模型、调试火山引擎/方舟/Ark 认证问题、用户提到 VLCES_API_KEY 或要在脚本/代码中接入豆包 GLM Kimi DeepSeek MiniMax 等 API 时，都应主动使用本 skill；用户想探索方舟平台其他能力（embeddings、结构化输出等）时也从这里的探索入口开始。
---

# llm-access — 火山方舟 Agent Plan LLM 调用

调用方式已全部实测验证（2026-09），固化在 `scripts/ark.py` 中。**优先用这个 CLI 而不是手写 curl**：它内置了 key 解析、思考模型的坑、错误诊断提示。

## 快速调用

```bash
S=~/.claude/skills/llm-access/scripts/ark.py

python3 $S chat '你好，介绍一下你自己'          # 默认模型 GLM-5.3-Flash
python3 $S chat -m GLM-5.3 '复杂推理问题...'     # 换模型
python3 $S chat -s '你是资深翻译' '翻译这段话'    # 带 system
echo '长文本...' | python3 $S chat               # stdin 传长文本
python3 $S chat --raw-json '...'                 # 看完整响应（含 usage/思考块）
python3 $S stream '讲个故事'                     # 流式逐字输出
```

## 核心事实（都是踩过坑的）

1. **端点是 `https://ark.cn-beijing.volces.com/api/plan`**，Agent Plan 套餐专用。通用的 `/api/v3` 会返回 `AuthenticationError`——key 本身没问题，是端点不对。
2. **认证**：key 在环境变量 `VLCES_API_KEY`（定义于 `~/.zshrc`），CLI 会自动解析（环境变量优先，兜底读 zshrc）。`x-api-key` 和 `Authorization: Bearer` 都能用。
3. **所有模型强制思考，不可关闭**（`thinking.type: disabled` 会报 `InvalidParameter`）。思考也消耗 `max_tokens`，所以：
   - `max_tokens` 给足：短问答 ≥512，正式任务 ≥1024，长输出 ≥2048
   - 解析响应只取 `type=="text"` 的内容块，`thinking` 块要跳过
   - 若 `stop_reason=="max_tokens"` 且 text 为空，就是额度被思考吃光了，调大重试
4. **两种协议任选**：Anthropic 协议 `POST /v1/messages`（CLI 默认用这个）；OpenAI 协议 `POST /v3/chat/completions`（思考内容在 `reasoning_content` 字段）。OpenAI 协议方便直接复用 openai SDK：`base_url=".../api/plan/v3"`。
5. **没有模型列表接口**（`/models` 404），模型清单用 `python3 $S models` 查看；新模型名用 `python3 $S probe <名字>` 探测（套餐外的模型返回 `UnsupportedModel`）。**probe 对带后缀的变体名会假阳性**：端点宽松匹配（2026-10-17 实测 `DeepSeek-V4.1-Flash-9999`/`-foobar`/`GLM-5.3-Flash-1017` 都返回可用）——探测「新版本号快照」（如 -1017）必须做对照实验（同前缀 + 荒谬后缀），全过说明只是前缀匹配到基础版，不能证明新快照存在。

## 可用模型（实测确认）

| 模型 | 定位 | AFP 系数（输入/输出，每百万 token） |
|---|---|---|
| `doubao-seed-2.0-mini` | 豆包极速，套餐内最便宜 | 0.25 / 0.25 |
| `GLM-5.3-Flash` | **默认首选**，快速便宜，原生多模态可图片输入 | 0.5 / 0.5 |
| `doubao-seed-2.0-lite` | 豆包标准，可图片输入 | 0.5 / 0.5 |
| `DeepSeek-V4-Flash` | DeepSeek 标准 | 0.5 / 0.5 |
| `DeepSeek-V4.1-Flash` | DeepSeek 快速，原生视觉理解可图片输入 | 2.5 / 2.5（限时 1.25 至 09-28） |
| `MiniMax-M3` | MiniMax 旗舰 | 2.5 / 2.5 |
| `doubao-seed-2.1-turbo` / `doubao-seed-evolving` | 豆包进阶，可图片输入 | 2.5 / 2.5 |
| `GLM-5.3` | 智谱旗舰，质量最高 | 4.5 / 4.5 |
| `Kimi-K2.7-code` | 月之暗面代码向 | 4.5 / 4.5 |
| `DeepSeek-V4-Pro` | DeepSeek 进阶 | 5.5 / 5.5 |
| `Kimi-K2.8-preview` | 月之暗面进阶 | 8 / 8（限时 4.8 至 09-30） |
| `Kimi-K3` | 月之暗面旗舰，套餐内最贵 | 10 / 10 |

另有 `GLM-5.3-Air`、`GLM-5.2`、`MiniMax-M3-Flash`、`Kimi-K3-Flash`、`doubao-seed-2.0-code`（按输入长度分档计费）实测可调用，但官方系数表未列出其系数。

**计费要点（AFP，2026-09 查官方文档）**：
- 套餐按 AFP 积分抵扣，非按 token 原样计数；`AFP = 输入token×输入系数 + 输出token×输出系数`（百万 token 计）。**思考 token 按输出计**，强制思考模型实际消耗高于表面系数。
- 额度限制：月额度（Small 2 万 / Medium 10 万 / Large 25 万 / Max 50 万 AFP）+ 5 小时额度 + 周额度；视觉模型另有日额度。
- 系数会调整（限时折扣、新模型上线），以官方[抵扣规则文档](https://www.volcengine.com/docs/82379/2516283)为准。

**图片输入（视觉）已实测**：`/v1/messages` 直接发 `{"type":"image","source":{"type":"base64","media_type":"image/png","data":"..."}}` 内容块即可，`glm-5.3-flash`、`doubao-seed-2.0-lite`、`doubao-seed-2.1-turbo`、`doubao-seed-evolving`、`deepseek-v4.1-flash` 均验证通过（截图代码复原测试全部正确）。图片按 token 折算计入输入。

模型更新很频繁——若某模型返回 `UnsupportedModel`，用 `probe` 探测新名字（可参考方舟文档的模型公告），探到后更新本清单和 `ark.py` 里的 `MODELS` 字典。

## 探索其他能力（--help 式检索）

```bash
python3 $S --help        # 总览所有子命令
python3 $S endpoints     # 能力清单：已验证✅ / 待探索⚠️ / 不可用❌ + 文档链接
python3 $S raw /v3/embeddings -d '{"model":"...","input":["hi"]}'   # 对任意端点发实验请求（自动带认证）
python3 $S raw /v1/messages -d '{...}' --stream                     # SSE 方式试流式
```

`endpoints` 是探索入口：实测发现 `/v3/embeddings` 路由存在（返回 `UnsupportedModel` 而非 404），但 `doubao-embedding` 模型名不在套餐内，其他 embedding 模型名可用 `raw` 继续试。Files API、上下文缓存、Responses API 未验证。套餐用量查询等管控面 API 需要 AK/SK 签名，本 skill 不覆盖。文档：<https://www.volcengine.com/docs/82379/2366394>

## 错误速查

| 错误码 | 原因 | 处理 |
|---|---|---|
| `AuthenticationError` | key 无效或端点用了 `/api/v3` | 确认走 `/api/plan`，检查 VLCES_API_KEY |
| `UnsupportedModel` | 模型不在套餐内 | `probe` 换模型名 |
| `InvalidParameter` | 如试图关闭 thinking | 移除该参数 |
| `stop_reason=max_tokens` 空文本 | 思考吃光额度 | 调大 `--max-tokens` |
| `400 Model only support text input` | 当前模型是纯文本模型，不接受 image 块（与请求格式无关） | 从上面已实测视觉模型清单换一个；批量图片任务前先用一张小图探针验证，不要反复重试同一模型或改请求体 |
| `400 SensitiveContentDetected` | 内容安全确定性拒绝（某些敏感条目会反复命中） | 直接跳过不重试——重试 4 次×退避每条浪费 ~10 分钟 |
| `429 weekly usage quota` | 周配额耗尽（响应含重置时间戳） | 等重置或换模型；耗尽时所有分片同时报错刷屏 |

## 批量长跑故障语义（GLM-5.3-Flash 批量评分/长跑实测）

- **max_tokens 必须 ≥12000**：GLM-5.3-Flash 强制思考，加证据分级等指令后思考更长；默认 6000 会让 JSON 被思考吃光截断，解析失败率 ~50-60%。启动长跑前显式确认该参数（曾因启动命令漏带吃了默认值）。结构化 JSON 输出参考上文的 16000 起步值
- **400 SensitiveContentDetected 是确定性拒绝**：直接跳过不重试
- **429 weekly usage quota 是周配额**：看响应里的重置时间戳
- **temperature=0 ark 接受**（HTTP 200），可用于评分稳定性
- **网络瞬断特征**：全部分片在同一秒集体停止、日志尾部 Connection refused——不是 ark 拒绝。对策：checkpoint + 已评条目幂等合并续跑 + 重试包装器（注意 max_tokens 是 keyword-only 参数，wrapper 别按位置传）

<!-- 来源: session a96f8e6f, cand-b519ce, 理由: 五类故障各自收敛出对策（尤其 400 确定性拒绝与 max_tokens），ark 长跑环境级事实 -->

## 模型规格与 1M 上下文（实测）

- GLM-5.3 / GLM-5.3-Flash / GLM-5.2 / MiniMax-M3 / Kimi-K3：1M 上下文 / 128k 最大输出
- **DeepSeek-V4.1-Flash：1M / 384k（输出额度是其他模型 3 倍，长输出任务首选）**
- GLM-5.3-Air / MiniMax-M3-Flash / Kimi-K3-Flash：探测可用但官方未收录，规格不明，不作主力
- 方舟 Anthropic 协议端点（/v1/messages）**原生支持 1M 上下文，无需 context-1m beta header**（实测 ~112 万字符 payload、250,018 input_tokens 返回 200）
- 方舟文档站是 JS 渲染 SPA，curl 抓不到正文，规格信息用搜索获取
- 结构化 JSON 输出给 GLM-5.3-Flash 时 `max_tokens` 起步 16000（强制思考烧预算，6000 时 ~65% 响应截断）；解析失败先怀疑截断而非提示词

## 重代码生成任务的模型行为差异（2026-10-18 异步 FIFO RTL 标准测试实测）

标准测试用例在 `~/model-eval/rtl-async-fifo/`（SPEC + 固定 prompt + 功能 TB + 流式运行器），可复用于任何模型对比。

- **GLM-5.3 思考失控**：重代码生成（读完 8 页 spec 写 300 行 RTL）下思考 5 万~6.5 万+ token，max_tokens=65536 时 temp 0 和默认温度都整段截断（正文 0 字、思考尾部是「再完整写一遍检查」循环）。给 128k 满额预算可完成（实测 54706 token / 593s）。同参数两次运行思考量波动 65k+ vs ~50k，方差极大，必须预设截断重试。
- **DeepSeek-V4.1-Flash 稳定**：同任务 3/3 次在 22k–29k token / 92–131s 内完成，质量全过功能仿真。重生成任务首选。
- **方舟 temp 0 ≠ 确定性**：同请求两次输出显著不同（token 数、代码风格均异），模型对比必须多次取样，byte 级 diff 无判别力。
- **长生成必须走流式**：GLM-5.3 非流式整段响应 >900s 会读超时（urllib timeout 是整段读等待）；SSE 分块到达则无此问题。流式运行器模板见 `~/model-eval/rtl-async-fifo/stream_eval.py`（含 usage 捕获、首字延迟、temp 可选）。
- **方舟自动 prompt 缓存**：非流式 usage 里 `cache_read_input_tokens` 单列，input_tokens 只剩几十——统计总输入必须三字段相加。

<!-- 来源: session f51e6f85 + a96f8e6f + 9e687bbb, cand-d35837+cand-33a794+cand-fb9ffb, 理由: 实测双重确认的选型关键参数 -->

网络方面直连即可，无需代理；走本机代理（127.0.0.1:7897）也已验证不影响。
