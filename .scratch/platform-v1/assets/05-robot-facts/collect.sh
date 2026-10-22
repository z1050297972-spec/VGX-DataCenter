#!/usr/bin/env bash
# 工作站侧包装：测连通、时钟偏差、吞吐，并远程执行 robot_probe.sh。服务于决策票「两台机器人的事实」。
# 用法：bash collect.sh <r1lite|autolife> <user@host> [远程脚本，默认 robot_probe.sh]
# 输出：本目录 out/<kind>-<时间>.txt。密码只在建立 SSH 主连接时输入一次。
set -u
kind=${1:?用法: collect.sh <r1lite|autolife> <user@host>}
target=${2:?用法: collect.sh <r1lite|autolife> <user@host>}
probe=${3:-robot_probe.sh}
host=${target#*@}
here=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$here/out"
log="$here/out/$kind-${probe%.sh}-$(date +%Y%m%dT%H%M%S).txt"
# ControlPath 有 108 字节上限，scratchpad 路径太长，放到 XDG_RUNTIME_DIR
sock="${XDG_RUNTIME_DIR:-$HOME/.ssh}/rdp-probe-%C"
exec > >(tee -a "$log") 2>&1

sec() { printf '\n===== %s [%s] =====\n' "$1" "$(date '+%F %T.%3N %z')"; }
run() { printf '\n$ %s\n' "$1"; eval "$1" 2>&1; printf '[rc=%s]\n' "$?"; }

sec "工作站侧 kind=$kind target=$target probe=$probe"
run 'ip -br addr'
# 关键：路由是否经过 Clash 的 TUN 网卡 Meta（经过的话 ping 可能被 TUN 假应答，吞吐也受影响）
run "ip route get $host"
run 'nmcli -t -f ACTIVE,SSID,CHAN,FREQ,RATE,SIGNAL device wifi list --rescan no 2>/dev/null | grep "^yes"'
run 'for i in enp4s0 wlp3s0; do printf "%s operstate=%s speed=%s\n" "$i" "$(cat /sys/class/net/$i/operstate 2>/dev/null)" "$(cat /sys/class/net/$i/speed 2>/dev/null)"; done'
run 'timedatectl 2>&1 | grep -iE "synchronized|NTP service|Time zone"'

sec "延迟：ping 20 次"
run "ping -c 20 -i 0.2 $host"

sec "建立 SSH 主连接（在这里输入一次密码）"
cleanup() { ssh -o ControlPath="$sock" -O exit "$target" >/dev/null 2>&1; }
trap cleanup EXIT
if ! ssh -o ControlMaster=yes -o ControlPath="$sock" -o ControlPersist=30m -o ConnectTimeout=10 -fN "$target"; then
  echo "SSH 主连接失败，退出"; exit 1
fi
S=(-o ControlPath="$sock")

sec "时钟偏差：机器人时间 - 工作站时间（取 5 次里往返最短的一次）"
best_rtt=999; best_off=0
for _ in 1 2 3 4 5; do
  t0=$(date +%s.%N); r=$(ssh "${S[@]}" "$target" 'date +%s.%N'); t1=$(date +%s.%N)
  read -r rtt off < <(awk -v a="$t0" -v b="$t1" -v r="$r" 'BEGIN{printf "%.6f %.6f\n", b-a, r-(a+b)/2}')
  printf 'rtt=%ss offset=%ss\n' "$rtt" "$off"
  if awk -v x="$rtt" -v y="$best_rtt" 'BEGIN{exit !(x<y)}'; then best_rtt=$rtt; best_off=$off; fi
done
printf '采用：offset=%ss（误差约 ±%ss）\n' "$best_off" "$(awk -v x="$best_rtt" 'BEGIN{printf "%.6f", x/2}')"

sec "远程采集 $probe（约 5–15 分钟）"
ssh "${S[@]}" "$target" "bash -s -- $kind" < "$here/$probe"
echo "[remote rc=$?]"

sec "吞吐：机器人 → 工作站，经 SSH 拉 100 MiB 零字节，3 次"
for i in 1 2 3; do
  t0=$(date +%s.%N)
  n=$(ssh "${S[@]}" -o Compression=no "$target" 'head -c 104857600 /dev/zero' | wc -c)
  t1=$(date +%s.%N)
  awk -v a="$t0" -v b="$t1" -v n="$n" -v i="$i" 'BEGIN{printf "第 %d 次：%d 字节，%.2f 秒，%.1f Mbit/s\n", i, n, b-a, n*8/(b-a)/1e6}'
done
echo "注：SSH 加密会占用机器人 CPU，所以这里测到的是下限。"

sec "完成，输出在 $log"
