# 只读：eth1 为什么断开（链路、载波、NetworkManager 状态、地址来源）。
set -u
sec() { printf '\n===== %s =====\n' "$1"; }
sec 时间; date -Is
sec "ip link eth1"; ip -d link show eth1 | head -3
sec "载波与状态"; for f in operstate carrier speed duplex; do printf '%s=%s\n' "$f" "$(cat /sys/class/net/eth1/$f 2>&1)"; done
echo "carrier_changes=$(cat /sys/class/net/eth1/carrier_changes 2>&1) carrier_up=$(cat /sys/class/net/eth1/carrier_up_count 2>&1) carrier_down=$(cat /sys/class/net/eth1/carrier_down_count 2>&1)"
sec "NetworkManager 设备"; nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status 2>&1 | head -12
sec "eth1 相关连接配置（只看方法和地址）"; for c in $(nmcli -t -f NAME,DEVICE connection show 2>/dev/null | awk -F: '$2=="eth1"||$1~/eth1|Wired|有线/{print $1}' | sort -u); do echo "[$c]"; nmcli -t -f connection.interface-name,connection.autoconnect,ipv4.method,ipv4.addresses connection show "$c" 2>&1; done
nmcli -t -f NAME,TYPE,DEVICE,AUTOCONNECT connection show 2>&1 | head -12
sec "netplan / interfaces 里的 eth1（只读）"; grep -rn 'eth1\|10\.42\.0' /etc/netplan /etc/network/interfaces /etc/network/interfaces.d 2>/dev/null | head -10
sec "最近 eth1 链路日志（不需要 root 的部分）"; journalctl -b --no-pager -o short-iso 2>/dev/null | grep -iE 'eth1' | tail -12
