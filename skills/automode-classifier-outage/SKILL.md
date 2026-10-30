---
user-invocable: false
name: automode-classifier-outage
description: 当 Claude Code auto mode 权限分类器反复超时（"temporarily unavailable (timed out)"）导致 Bash 持续被拒，或收到带理由的 automode-blocked 拒绝时，按阶梯拆小命令重试、延后非阻塞项、交用户手动执行或索取显式授权。
metadata:
  provenance: self-improving-skills

---
# automode-classifier-outage — auto mode 分类器故障应对

以下打法在 2026-09-24 telegram-gateway 切换 session（5ce5690a）中经十余次超时实测验证。

## 关键认知

- 故障**间歇且与命令形状相关**：trivial 命令（`echo`、`pwd`、`git init`）常能通过；复合命令（`&&` 串联、heredoc、多行 commit message）、`git add -A` / `git add .`、含敏感字样（apiKey/token/写 .env）的命令更容易超时或被拦。同一命令换个时刻结果不同——是抽风，不是封禁。
- 报错本身会提示：只读操作（读文件、搜代码）**不经分类器**，随时可用，也是垫时间的手段。
- 不经 Bash 的工具不受影响：TaskStop 停后台任务、Write 写非敏感文件都照常工作。

## 应对阶梯（按序升级，勿跳级硬绕）

1. **探测**：跑一条 trivial 命令（如 `echo probe`）判断分类器当前状态，再决定重试还是绕行。
2. **拆小**：把复合命令拆成单条串行执行；用显式文件列表 `git add <files>` 代替 `-A`/`.`；多行 commit 缩成单个短 `-m`。实测显式列表通过率明显更高。
3. **垫时间重试**：只读操作或 `sleep` 后重试原命令（故障窗口通常分钟级），同一命令最多重试 2–3 次。
4. **延后**：非阻塞收尾（git 提交、key 写入）记入待办清单（README/任务），继续主线，分类器恢复后再补。
5. **交用户**：持续失败就把精确的手动命令逐条写给用户执行，不要无限重试恋战。

## 带理由的拒绝 ≠ 超时

`automode-blocked` 给出实质理由（如"终止了本会话未创建的 launchd 服务，需用户显式点名授权"）时，**不要换工具绕过**。正确路径：把理由转述给用户 → 索取对该具体动作的明确授权（点名服务/动作）→ 拿到后再执行。实测这条路径成功解锁了停服切换；分类器拦得有理时它本身就是安全边界，用户授权后同类命令立即放行。

## 反模式

- 被拒后原样重放同一条命令刷通过率（本 session 实测基本无效，纯耗时）。
- 把敏感操作伪装成测试/只读形态骗过分类器。
- 含 key 的配置写入：代码里只要出现 `apiKey` 字样，Write 和 Bash 都可能被误拦——此时最省事的是交用户手动加一行。

<!-- 来源: session 5ce5690a（telegram-gateway 三 bot 切换）, 理由: 分类器故障应对为类级可复用技术，本机 MiniMax 分类器间歇故障反复出现，且阶梯与授权路径均有成失败对照实测 -->
