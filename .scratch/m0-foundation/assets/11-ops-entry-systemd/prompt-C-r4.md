评审第 4 轮（一键脚本这一段）。本段 3 轮已用满，负责人授权执行线决定加这一轮。只有一项阻塞。

在 `67271a2` 上跑验收 9：问答段已经全部通过（`drill9q-run.log`）。但两次完整运行都卡在 GitHub API 未认证限流（`drill9-run-67271a2-ratelimited*.log`）：
```
已被GitHub限流；响应头给出的可重试时间（UTC）：2026-10-29T05:32:36.000Z；……
```
限流提示本身是对的。问题是方案依赖 `api.github.com` 取 release 元数据，同一 IP 每小时只有 60 次。用代理、共享出口或者公司网络的机器，第一次安装就可能失败。这不能靠"稍后重试"解决。

**修法（执行线已决定）**
- uv、pnpm 的 SHA256 按架构固定在脚本顶部，和版本表放在一处、只有一份。值由执行线从官方 release 的 asset digest 读取，并核对过两次：
  ```
  uv 0.13.5   uv-x86_64-unknown-linux-gnu.tar.gz   f68d291c75783122dad58ab77def0e13f3233f358731db5d6d7e8715603b928f
  uv 0.13.5   uv-aarch64-unknown-linux-gnu.tar.gz  4bb69cf95ed13f23713bb7bc09f241896ea0c75b7c557e615a20604b82f9c403
  pnpm 11.22.0 pnpm-linux-x64.tar.gz              4c592fa410eb23b69691a9efb9bf21c87c15b3e9d88c6ec8acdd354a0eb8de71
  pnpm 11.22.0 pnpm-linux-arm64.tar.gz            f1426231f365bdfd46c15fa3d1211c3936ee2c4e557afd304f6c66dbf1b2a8bf
  ```
- 下载地址改成 `https://github.com/<owner>/<repo>/releases/download/<tag>/<asset>`。这个地址会 302 到 `release-assets.githubusercontent.com` 或 `objects.githubusercontent.com`，不占 API 额度。
  - 允许的主机加上 `github.com`，重定向白名单照旧。
  - 不再请求 `api.github.com`，删掉 `read_official_release_digest` 里取元数据和用 Node 解析的部分，换成查固定表。
- 第 2 轮做的限流诊断：如果新的下载路径上不会再遇到 API 限流，就删掉；如果 github.com 的下载地址也可能返回 403 或 429，就保留通用的"403/429 明确提示"，只是不再特指 API 限流。
- 帮助文本里 uv、pnpm 两行的来源描述同步改：从"GitHub release metadata 的 digest"改成"脚本内固定的 SHA256、github.com releases 下载地址"。在第 3 块列出原句和新句。
- 以后升级版本时，要同时更新版本和 SHA256 两张表。在版本表上方的注释里写一句。
- Node 的做法不变，仍然用同源的 SHASUMS256.txt。

**测试**
- 假 curl 要能断言：脚本从不请求 `api.github.com`；请求的是 releases/download 地址；重定向到白名单之外的主机时拒绝。
- 固定摘要不匹配时停下，不发布工具。
- 删掉或改写只适用于 API 元数据的测试。

**要求**
- 先红后绿。
- 只改 `scripts/setup.sh`、`tests/`。
- 最后跑一次 `make check`，0 skipped。
- 边界同前：不联网（摘要已经给出），不 `git add`、不提交、不安装，不调用真实 systemctl、loginctl，不碰真实 `~/.config`、`~/.local`，不碰 `/mnt`。

30 分钟内交付。最终回复五块，第 1、5 块只写本轮。
