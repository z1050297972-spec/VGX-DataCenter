#!/usr/bin/env bash
# R1 Lite 的 eth1（接主臂电脑）链路排查（只读），服务于「机器人现场补测」。
# 背景：10-21 早上主臂一直开着、网线一直插着，eth1 却是 NO-CARRIER，节点互相不通；晚上 eth1 正常拿到 10.42.0.238。
# 本脚本查三件事：eth1 是什么网卡、本次开机以来链路断过几次、内核和 NetworkManager 日志里 eth1 何时 up/down。
# 用法：bash collect.sh r1lite nvidia@<IP> eth1_probe.sh
#
# 只读：不写文件、不用 sudo、不改网络配置。读不到的日志（权限不够）会如实报错，不重试。

main() {
  sec "开始 eth1_probe（第 1 版）"

  sec "开机时间"
  run 'uptime -s; uptime'
  run 'journalctl --list-boots --no-pager 2>&1 | tail -n 6'
  run 'last -x reboot shutdown 2>&1 | head -n 10'

  sec "eth1 是什么网卡"
  run 'ip -br link show eth1; ip -br addr show eth1'
  run 'readlink -f /sys/class/net/eth1/device; basename "$(readlink -f /sys/class/net/eth1/device/driver)"'
  run 'udevadm info -q property -p /sys/class/net/eth1 2>&1 | grep -E "^(ID_BUS|ID_VENDOR|ID_MODEL|ID_NET_DRIVER|ID_PATH|ID_USB_DRIVER)="'
  run 'command -v ethtool >/dev/null && ethtool eth1 2>&1 | grep -E "Speed|Duplex|Auto-negotiation|Link detected"'

  sec "本次开机以来的链路计数"
  run 'for k in operstate carrier carrier_changes carrier_up_count carrier_down_count speed duplex; do printf "%s=%s\n" "$k" "$(cat /sys/class/net/eth1/$k 2>/dev/null)"; done'
  run 'ip -s link show eth1'

  sec "eth1 对端（主臂电脑）"
  run 'ip neigh show dev eth1'
  run 'nmcli -t -f GENERAL.DEVICE,GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS,IP4.GATEWAY,DHCP4.OPTION device show eth1 2>&1 | grep -vE "DHCP4.OPTION.*(requested|next_server)" | head -n 30'
  run 'ping -c 3 -W 1 10.42.0.1'

  sec "内核日志里的 eth1（近 2 天）"
  run 'journalctl -k --since "2 days ago" --no-pager -o short-iso 2>&1 | grep -iE "eth1|link (is )?(up|down)|r8152|r8169|igb|ax88" | tail -n 60'
  run 'dmesg -T 2>&1 | grep -iE "eth1|link (is )?(up|down)" | tail -n 30'

  sec "NetworkManager 日志里的 eth1（近 2 天）"
  run 'journalctl -u NetworkManager --since "2 days ago" --no-pager -o short-iso 2>&1 | grep -iE "eth1|10\.42\.0\." | tail -n 80'

  sec "结束"
}

sec() { printf '\n===== %s [%s] =====\n' "$1" "$(date '+%F %T.%3N %z')"; }
run() { printf '\n$ %s\n' "$1"; eval "$1" 2>&1; printf '[rc=%s]\n' "$?"; }

main "$@" </dev/null
