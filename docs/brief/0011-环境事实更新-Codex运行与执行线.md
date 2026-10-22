# 0011 环境事实更新：Codex 运行与执行线

> 类别：输入（只追加，不改写）。记录日期：2026-10-22。
> 本文补充 0006、0009，来自规划和执行并行后第一天的实测。Codex 的运行日志留在临时目录，没有入库；提示词和最终回复存在 `.scratch/platform-v1/assets/job-queue-research/` 和 `.scratch/platform-v1/assets/16-dataset-browser/`。

## 模型与网关

- **默认配置**：`~/.codex/config.toml` 里默认 `model = "gpt-6-astra"`、`model_reasoning_effort = "high"`，provider 是 custom，`wire_api = "responses"`，`base_url` 是局域网地址 `http://192.168.0.180:8088`。
- **显式参数可用**：
  - 命令里显式写 `-m gpt-6-astra -c model_reasoning_effort='"high"'`，能正常调用：只读的冒烟测试回复了 OK。
  - `codex exec resume` 同样有 `-m` 参数（codex-cli 0.163.0 的 `--help`）。
- **一次网关故障**（约 05:00）：
  - 经过代理 `127.0.0.1:7897` 访问网关时超时：curl 等了 8 秒没有响应。直连能通，0.6 秒就返回了 302。
  - Codex 报 "stream disconnected before completion: error sending request"，重连到第 4/5 次，最后超时。
  - 负责人修好后恢复正常。具体原因（代理规则还是网络环境）没有查。
- **当时的网络和 0002、0007 记的不一样**：Wi-Fi `wlp3s0` 的地址是 10.1.179.3/16，另外多了一块 `enxf681c4ced907`，地址 172.20.10.3/28，看起来是 USB 共享的手机热点。
- **一条无害的警告**：配置里的 `disable_response_storage` 已经被 Codex 忽略，每次运行都会报一条警告，不影响运行。
- 来源：`codex exec --help`、`codex exec resume --help`、`curl --noproxy '*'` 和经代理的 `curl` 对比、`ip -br addr`、`ip route get 192.168.0.180`。

## 运行方式

- **不是 git 仓库的目录**：在这类目录里运行 `codex exec`，要加 `--skip-git-repo-check`，否则会报 "Not inside a trusted directory and --skip-git-repo-check was not specified."。
- **标准输入要接上**：没接上时，`codex exec` 会打印 "Reading additional input from stdin..." 然后一直等。可以用 `< /dev/null`，或者从文件读提示（`- < prompt.md`）。
- **沙箱里不能建 socket**：
  - 在 `workspace-write` 沙箱里，`pnpm build` 会输出 "Failed to create stream fd: Operation not permitted"，但不影响构建。
  - 本地 HTTP 服务也起不来，所以 Codex 没法在沙箱里打开页面做实测。
- **联网调研的证据不全**：运行日志里的 `web_search` 事件只记查询，不记返回的内容，所以没法凭日志核对 Codex 从网上读到了什么。这次作业队列调研里，Codex 发起了 14 次搜索；版本、日期、维护状况这些联网事实，最后由 Claude 补查核对。

## Claude 的使用额度

- **中断**：约 06:00 起，三个后台 agent 都因为 Claude 的使用额度用完（HTTP 429，"You've hit your session limit"）中途停下。额度在 07:10（本机时区）恢复。
- **恢复**：已经做的工作都还在。agent 的上下文保留着，发一条续接消息，它就能从停下的地方接着做。它派出的 Codex 进程不受影响：原型那一轮照常在 06:03 跑完。
- **启示**：执行线的每一步都要把产物落到文件里，不能只留在 agent 的上下文中（已写进 `docs/agents/codex-workflow.md` 草稿）。
