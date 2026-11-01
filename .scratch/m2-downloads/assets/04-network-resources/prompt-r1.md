执行线在本机做了浏览器演练，发现 VPN 检测在真实环境里漏判。当时本机开着 Clash Verge，页面却显示"隧道网卡：off；代理进程：off"。事实如下：
- `ip -br link` 里有一块叫 `Mihomo` 的 TUN 网卡（`/sys/class/net/Mihomo/tun_flags` 存在，`type` 是 65534），名字不是 tun/tap/wg 开头。
- `tailscale0` 也是 TUN 网卡（同样有 `tun_flags`），但它是负责人 SSH 登录用的 Tailscale，不代表全局代理，不能算成"开了 VPN"。
- 实际的代理进程名（`ps -eo comm`）是 `verge-mihomo`、`clash-verge`、`clash-verge-ser`（comm 最长 15 个字符会被截断）。

逐条修复，别处不动：
1. 隧道网卡改成按 `/sys/class/net/<名字>/tun_flags` 是否存在来判断（保留 wg 前缀判断，WireGuard 没有 tun_flags）；排除名字以 `tailscale` 开头的网卡，写成具名常量并注明理由（负责人经 Tailscale SSH 登录，它不改默认路由）。
2. 代理进程改成子串匹配：进程名包含 `mihomo`、`clash`、`v2ray`、`xray`、`sing-box` 任一（不区分大小写）就算开。
3. 测试：用假的 `/sys/class/net` 目录（`Mihomo` 带 tun_flags 判开；只有 `tailscale0` 带 tun_flags 判关）和进程名 `verge-mihomo`、`clash-verge-ser` 各补一个用例。

修完 `make check` 一次全绿就交。最终回复第一行写 `状态：全部完成`，后面写改了什么和 `make check` 末尾输出。边界不变：只改 `src/`、`tests/`，不 git add、不提交，不碰 `/mnt` 和两个旧项目，不安装、不访问网络。
