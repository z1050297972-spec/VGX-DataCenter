状态：全部完成

- 网卡按 `tun_flags` 判断，保留 `wg` 前缀；通过具名常量排除 Tailscale，并注明 SSH 用途。
- 代理进程改为忽略大小写的关键词子串匹配。
- 补齐 `Mihomo`、`tailscale0`、`verge-mihomo`、`clash-verge-ser` 回归用例。
- 仅修改检测模块及对应测试，未暂存、未提交。

`make check` 完整复跑全绿：pytest 2740 项通过。首次检查中既有 FileViewer 用例失败，单独及完整复跑均通过，未修改该处。

末尾输出原样：

```text
 Test Files  41 passed (41)
      Tests  379 passed (379)
   Start at  03:31:15
   Duration  12.31s (tests 58%, import 22%, environment 19%, transform 1%)
```