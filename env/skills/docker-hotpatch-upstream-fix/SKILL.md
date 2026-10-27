---
user-invocable: false
name: docker-hotpatch-upstream-fix
description: 当运行中的第三方自托管 Docker 容器里的应用有 bug，上游仓库已有修复（未合并的 PR 或比镜像新的 master）但没有任何发版镜像包含它，需要把补丁安全地热打进运行中的容器时使用：版本漂移比对、免认证拉 PR patch、容器内语法校验、数据卷备份与重启验证。
metadata:
  provenance: self-improving-skills
---

# docker-hotpatch-upstream-fix — 给运行中的容器热打上游补丁

自托管第三方服务（we-mp-rss 这类）出 bug 时，修复常在 upstream 的 PR 或 master 里，但镜像停在旧 commit 且短期不会发版。与其换镜像/等发版/Fork 自建，不如把补丁直接热打进容器。2026-10-08 在 we-mp-rss（上游 PR #470 修 200013 降级链提前 break 的 bug）实测全链跑通，关键步骤与坑如下。

## 流程

1. **先测版本漂移，别信 tag 标签**：`docker cp <c>:/app/<pkg> /tmp/orig` 拉出容器内代码，与 upstream clone `diff -rq` 对比。镜像实际 commit 可能比 release tag 新（本次容器 v1.5.3 标签实际已含降级链代码，只缺那个 PR 的 fix）——漂移测错会导致补丁选错或白打。
2. **验证补丁依赖面**：diff 两边 `requirements.txt` + grep 补丁新增的顶层 import。新 import 全部落在容器已有 venv 里才可热补；若补丁引了新依赖且只影响无关功能，仍可只挑相关文件。
3. **拉 PR patch 免认证**：`https://github.com/<owner>/<repo>/pull/<N>.patch`（`curl -sL -o pr.patch`）。api.github.com 匿名请求很快限流（60 次/h），.patch 端点不走 API 配额。下载后 `grep -c "^diff --git"` 确认非空且涉及文件符合预期。
4. **apply 后必须语法校验**：`git apply --check` 通过 ≠ 结果能跑。hunk 上下文漂移可让 git apply 成功却产出错误缩进（实测 IndentationError: unexpected indent）。流程：apply → 用**容器自己的 python** `py_compile` 每个改动文件 → 报错就手工修缩进 → 再验。修复后要人工核对缩进层级（fallback 调用该在哪个 if 块内）。
5. **备份进数据卷，不是 /tmp**：`docker exec <c> sh -c "mkdir -p /app/data/backup_<ver> && cp <files> ..."`。数据卷随容器重建保留，回滚和日后对账都靠它。
6. **打补丁 + 清缓存 + 重启**：`docker cp` 每个改动文件进容器 → `rm -rf <pkg>/__pycache__`（陈旧字节码会遮蔽新代码）→ `docker restart` → curl 探活。注意 busybox/alpine sh **不支持花括号展开**（`cp {a,b}` 报 cannot stat），文件名逐个写。
7. **用真实故障链路验证**：重启后登录态/token 通常在数据卷（Redis dump 等）里存活，但别假设——先打 auth verify 接口确认，再触发原来失败的那条真实流程，`docker logs --since` 盯关键日志行（本次看到"自动降级到 free_publish 多端点模式"逐端点尝试，证明补丁生效）。

## 判断

- 热补丁的价值不只是"修好"：本次补丁让降级链正确工作后，才拿到"全端点皆死"的铁证，把问题从"频控运气"定性为"定向封死"。验证类补丁（让错误路径完整暴露）也值得打。
- 补丁改动文件多且含前端 dist/锁文件（几百 diff）时放弃热补，考虑自建镜像。
- 容器重建后热补丁会丢：把打了哪个 PR、备份路径、补丁文件位置（/tmp 会跨天丢，挪到数据卷或项目目录）记进项目 memory。

实测：2026-10-08 we-mp-rss 容器热打 PR #470（api/app/free_publish/web.py 四文件），重启后降级链完整执行，token 存活，原文件备份在容器 `/app/data/backup_core_153/`（session 699ddb10）。

<!-- 来源: session 699ddb10（公众号 AI 库：mp 平台路由全灭定论）， 理由: 给运行中容器热打上游未发版补丁是类级操作（自托管服务出 bug、修复只在 PR/master、无发版镜像），含多个非显然坑（.patch 端点绕 API 限流、git apply 成功但缩进坏、busybox 无花括号展开、__pycache__ 遮蔽、备份进数据卷），现有技能（含 colima-rosetta-x86-docker，主题是架构转译）无一覆盖 -->
