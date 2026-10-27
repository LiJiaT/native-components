---
user-invocable: false
name: colima-rosetta-x86-docker
description: 在 arm64 Apple Silicon Mac 上跑 x86_64/amd64 Linux Docker 容器（尤其含 Playwright/Chromium/Xvfb 等浏览器引擎的镜像）反复 SIGSEGV 崩溃时使用：改用 colima+Rosetta 转译替代 qemu，并把浏览器二进制持久化进数据卷防重装。
metadata:
  provenance: self-improving-skills
---

# colima-rosetta-x86-docker — arm64 Mac 跑 x86_64 容器（Rosetta 转译）方案

qemu 用户态转译跑不动真实浏览器引擎：Chromium/WebKit/Xvfb 进程 SIGSEGV、Playwright `launch()` 反复失败、报 "Browser closed unexpectedly"。正确路径是 colima VM 开 Rosetta + 容器显式 `--platform linux/amd64`。2026-10-07 we-mp-rss（含 Playwright + Xvfb 的 x86_64 镜像）实测扫码登录链路全程跑通，关键点与坑如下。

## 配置步骤

1. **colima 开 Rosetta**：编辑 `~/.colima/default/colima.yaml` 设 `rosetta: true`（前提：macOS 13+、`softwareupdate --install-rosetta --agree-to-license`），然后 `colima stop && colima start`。也可启动时用 `colima start --vz-rosetta`（VM 类型需为 vz，不要停留在 qemu）。
2. **容器显式指定平台**：`docker run --platform linux/amd64 ...`。不指定时 arm64 主机会拉 arm64 变体（行为与 x86 版不同，如捆绑浏览器路径不一致）或退回 qemu 转译（必崩）。
3. 镜像内捆绑的 x86_64 浏览器二进制无需替换或重装——Rosetta 转译下直接运行。

## 坑

- **qemu 下浏览器必崩，别错怪应用**：先看 VM 转译层，再去换浏览器类型/降级 Playwright 版本，方向错了能耗掉几小时。
- **浏览器二进制持久化进数据卷**：把 Playwright 的浏览器安装目录（`PLAYWRIGHT_BROWSERS_PATH`）指向挂载卷，首次启动时装入卷内；之后容器删除重建（甚至换镜像 tag）浏览器仍在，秒级恢复。装进容器可写层则每次重建要重下几百 MB，且国内网络下常失败。
- **镜像可能同时捆绑多套浏览器路径**（如 we-mp-rss 的 `/app/env/driver/` 旧 webkit 与 `/app/data/pw-browsers` 新装 chromium）：Rosetta 下 webkit MiniBrowser 也能活，不必强改成 chromium；以进程表实测为准。
- **验证以真实链路为准**：`docker exec <c> ps aux` 看浏览器进程存活 + `docker logs` 跑一次真实登录/渲染流程，比任何 `--version` 自检都可信。
- colima VM 配置（CPU/内存/rosetta 开关）在 `~/.colima/default/colima.yaml`，重建 VM 前先备份；应用数据放独立数据卷，容器可随时删改不丢数据。

实测：2026-10-07 rachelos/we-mp-rss x86_64 镜像（Playwright + Xvfb + webkit/chromium + 微信扫码登录）在 colima 2C/3G + Rosetta 下链路全程跑通，浏览器装进数据卷后容器重建即恢复（session 699ddb10）。

<!-- 来源: session 699ddb10（公众号 AI 库 M1：we-mp-rss 部署）， 理由: arm64 Mac 跑 x86_64 浏览器容器是环境级反复出现的坑，qemu SIGSEGV→colima+Rosetta 修复 + 浏览器卷持久化是类级打法，现有 13 个 session 技能无一覆盖 Docker/容器/模拟转译主题 -->
