# Telegram bot 必须同时注册 /start 和文字兜底 handler

给 gateway 添加新 bot 身份时，除了业务命令 handler，必须同时注册：

1. `/start` 命令 handler——用户点 Telegram 蓝色 START 按钮会自动发出该命令
2. 文字消息兜底 handler（MessageHandler 过滤非命令文本）——回一句用法提示
3. **CallbackQueryHandler**（bot 带审批/交互按钮时）——inline 按钮回调只路由到发消息的那个 bot 本身，漏注册则按钮无处落地，180 秒超时自动拒绝，用户视角是「按钮点了没反应」
4. **装饰性外发调用单独容错**——流式回复链路里的 `send_chat_action`（「正在输入…」等）失败必须静默吞掉；核心发送重试 2 次后才放弃且不向上抛。否则代理抖动一次就炸掉整场已输出过半的回复

否则纯命令式 bot 对普通消息静默忽略，用户视角就是「bot 发消息没任何反应」，极易误判为 bot 挂了。

实证：2026-10-07 overseer 上线时漏掉前两项，用户连发数条消息无回应；同日补齐 /start + 兜底后，/nudge 审批按钮仍点不动（CallbackQueryHandler 缺失），且 16:13 一次代理抖动经 send_chat_action 异常穿透 StreamSender→run_query 炸掉整次回复。修复后代理再抖只延迟不丢消息。写 bot 配置时可对照 gateway.py 中 overseer 修复后的 handler 注册结构。

<!-- 来源: session 763ea9db, cand-e7ba41, 理由: 设计疏漏反复出现的形态，一条规则在下次加 bot 时杜绝 -->
<!-- 来源: session eb9ff48c, cand-59170a, 理由: 同一场景的第二、第三个坑，合并沉淀 -->
