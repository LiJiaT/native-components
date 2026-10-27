---
user-invocable: false
name: bg-cron-patrol
description: 在后台 Claude Code session 里用 cron 定时巡检长时间运行的分离批量任务（评分分片、批量抓取等）时使用，涵盖巡检 cron 选型与堆积恢复、分离进程幂等重启、配额阻塞处置与 /tmp 工具跨天丢失防护。
metadata:
  provenance: self-improving-skills

---
# bg-cron-patrol — 后台 session 分离任务 + cron 巡检作战方案

以下打法在 2026-09-27~28 radar v4 增量评分轮（session 4cb7ed56，4 分片 ×48 条 + sweep）全程实测：分片跑完→合并→渲染→全控件验证→报告，期间经历周配额 429 阻塞与 /tmp 工具丢失两次故障，均按本方案恢复。

## 巡检 cron 选型

- **优先链式 one-shot**：每次巡检用 `CronCreate(recurring:false)` 只排下一个检查点，未完再排下一个。session 空闲期（配额耗尽、API 中断）不会堆积无用 firing。
- **recurring cron 慎用**：session 被阻塞时它照样每周期 firing，全部排队成噪声。用的话，巡检 prompt 末尾必须写明"任务收尾后删除本 cron"。
- **堆积恢复**：恢复后发现队列压了 N 次相同 firing 时，只执行一次巡检体，然后 `CronDelete` 掉 recurring 任务；任务未完就改排一个 one-shot 继续。不要按 firing 次数重复执行巡检体。

## 巡检 prompt 模板（自包含）

每次 firing 都可能在新上下文里执行，prompt 必须自带全部信息，缺一不可：

1. 检查什么：各分片日志路径 + `[done]` 标记 + 进程存活（`ps aux | grep -c '[实际进程名]'`，注意 `[]` 防自匹配）；
2. 全部完成后做什么：按序编号的收尾清单（合并→空值校验→渲染→验证→前后对比→报告）；
3. 终态预期：哪些"失败"是预期终态（如内容过滤确定性拒绝项再次被拒不算失败）；
4. 异常处置：分片死亡则分离进程幂等重启；进度为 0 则先查日志再动作；
5. 收尾动作：删除本巡检 cron。

## 分离进程管理

- 启动：`nohup caffeinate -is <cmd> > /tmp/xxx.log 2>&1 & disown`（caffeinate 防休眠），日志末尾打 `[done] key=value` 摘要行（scored/failed/out 路径）供巡检 grep。
- **重启必须幂等**：输出靠 url_hash 去重或 `--out` 原地合并，重跑同一分片不产生重复数据——这是"分片死亡就重启"敢于成立的前提。
- **原生库易崩（torch/Docling segfault 等）加看护链，别等巡检发现**：启动时就包一层 shell 看护——`run_until_done` 循环：命令退出 0（真完成）才放行下一阶段，非 0（崩溃）则 sleep 60 重跑（上限 ~20 次防死循环）；幂等性由每篇/每分片的状态文件断点续跑保证。重启前先清掉崩溃时的在途半成品目录（目录已建但最终产物如 ir.json 缺失的），防止续跑误用残缺文件。实测 2026-10-07 AI 论文库流水线 39 篇处 segfault 一次，看护链续跑后 100+ 篇零重启（session 80e7b1c1）。
- **harness 托管的后台任务会被系统内存不足击杀**（报错 "stopped because the system is running low on memory"，与任务本身占用无关）。跨天长批次不要用 harness 托管，直接 nohup 一个监督循环：`for i in {1..60}; do <批次命令>; <完成判定，如 manifest 行数≥N 则 break>; sleep 30; done`——进程被杀/失败自动续跑（幂等前提同上）。实测 2026-10-07 photo2code 老批次被击杀两次后改此方案（session b5dfd8c8）。
- **杀监督进程不会杀其 worker 子进程**：重启/调参后必须 `ps aux | grep '[worker 名]'` 查孤儿并 pkill，否则新旧两组 worker 并发处理同一批次（重复写 manifest、烧双倍额度）。实测：kill 旧 supervisor 后其 python 子进程存活，与新起的并发重复转写。
- **重试/补跑轮必须逐项打成功/失败日志**：重试代码 except 后不打印 = 静默失败。实测 2026-10-08（session 80e7b1c1）21 篇补抽全部 rc=-11 失败而主日志零新增行，全靠状态文件计数未变才被察觉。每项要有可 grep 的结果行（如 `[noocr] aXXX OK/FAIL rc=N`）。
- **失败路径写状态记录要带全 identity 字段**（与成功记录同构）：stage A 失败记录缺 paper_id，补跑脚本按记录推目录拿到空值，21 篇产物全写进输出根目录互相覆盖（靠渲染只 glob 子目录才未污染站点）。
- **补跑失败项严禁与在跑批次并发写同一状态文件**（主 phase 每篇后 save_state，last-write-wins 互相覆盖）。标准做法是挂收尾看护：`while kill -0 <主链PID> 2>/dev/null; do sleep 300; done` 等主链退出后再按阶段补跑（各带 ~10 次重试上限循环），实测同 session 21 篇收编链。
- **输入内容触发的 native segfault，修库无效就加旁路开关**：换 opencv 版本后同一批 PDF 仍崩（RapidOCR/torch conv2d）——特定输入内容触发而非库版本问题。带文本层的 PDF（arXiv）可加 env 开关禁用 OCR（`PAPERLIB_NO_OCR=1` → `po.do_ocr=False`）绕开，实测 21/21 全过。库级修复必须用同一失败集重放验证，import 正常不代表修好。
- 瞬断失败项（网络/解析类）收尾时单独 sweep 一轮原地补跑；确定性 400 拒绝（内容过滤）记为预期终态，不再重试。

## 阻塞与恢复

- 429 周配额（`apiErrorIsTransient: false`）**不可重试**，等重置窗口即可；期间 cron firing 会排队，恢复后按"堆积恢复"三条处理。
- **重负载批次的"停滞"是正常态**：单条任务耗时 30-80 分钟（如视觉模型转写密集代码窗口，单条输出 6-9.5 万 token）时，2 小时巡检进度只涨 0-2 条不是故障。拉长巡检间隔到 3h，并在巡检 prompt 的"终态预期"里写明"X 小时只涨几张属正常"，防止未来 firing 误判乱干预。流式 HTTP 读超时按 chunk 语义：慢但持续出流的请求可合法跑 80+ 分钟，`read timed out` 只代表完全停滞；单轮 3 次超时失败交给监督循环下轮自动重捞。
- **提速权衡**：重启提并发会丢掉全部在途工作（每 worker 最多 30-60 分钟）；只有剩余量远大于在途成本（如 >10 倍）时才值得。
- 巡检命令避免 `sleep` 长等待吃 2 分钟超时（Exit 143）：要么分次短查，要么直接排一个 one-shot cron 到预估完成时刻。

## /tmp 跨天会丢（两次实锤）

macOS 定期清理 /tmp，跨天的工具（DOM stub、verify 驱动等）会被删掉。**工具一旦跑通，立刻固化进仓库**（如 tests_offline/），不要指望下次还在 /tmp。当天内的运行日志放 /tmp 没问题。

工具已丢时的重建路径：派子代理从模板/产物重建（prompt 里写全架构要点与已知坑——如 DOM stub 事件不冒泡、dispatch 要在容器上带 `{target: 按钮}`、断言末行 PASS 口径），主 session 并行做数据侧检查，互不等待。

<!-- 来源: session 4cb7ed56（radar v4 增量评分巡检 + 第四批改进）， 理由: 分离任务+cron 巡检是本机反复使用的工作形态，堆积恢复//tmp 丢失均有实锤代价，恢复打法经完整一轮验证 -->
<!-- 增补: session 80e7b1c1（2026-10-08 AI 论文库收尾）， 理由: 静默重试失败/状态记录缺字段/并发写状态文件/输入型 segfault 旁路四项均有实锤代价，打法经 21 篇补抽验证 -->
