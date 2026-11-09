#!/usr/bin/env bash
# M5：R1 Lite 现在能发现哪些节点（只读，负责人 2026-11-09 授权"再看一眼机器人上现在能发现哪些节点"）。
# 唯一写入：mktemp 临时目录（ROS 日志、XML 副本），结束时删除。不改配置、不发消息、不用 sudo、不起 ros2 daemon。
set -u
tmp=$(mktemp -d) || { echo "mktemp 失败"; exit 1; }
trap 'rm -rf "$tmp"' EXIT
export ROS_LOG_DIR="$tmp/roslog" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
mkdir -p "$ROS_LOG_DIR"
sec() { printf '\n===== %s =====\n' "$1"; }
xml=/opt/galaxea/find_server/super_client_profile.xml

sec "时间与网口"
date -Is; uptime
ip -br addr | grep -E '^(eth0|eth1|wlan0)'

sec "在跑的 ROS 相关进程：各自用哪种发现配置"
# 只取发现相关的环境变量，不打印其他内容
for pid in $(pgrep -u "$(id -u)" -f 'ros|HDAS|python3|_node' | head -80); do
  cmd=$(tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null | cut -c1-90)
  [ -n "$cmd" ] || continue
  envs=$(tr '\0' '\n' < /proc/$pid/environ 2>/dev/null | grep -E '^(FASTRTPS_DEFAULT_PROFILES_FILE|ROS_DISCOVERY_SERVER|ROS_SUPER_CLIENT|ROS_DOMAIN_ID|RMW_IMPLEMENTATION|ROS_LOCALHOST_ONLY)=' | tr '\n' ' ')
  [ -n "$envs" ] || continue
  printf '%s | %s | %s\n' "$pid" "$cmd" "$envs"
done | sort -t'|' -k3 | head -60
sec "按发现配置分组计数"
for pid in $(pgrep -u "$(id -u)" -f 'ros|HDAS|python3|_node'); do
  tr '\0' '\n' < /proc/$pid/environ 2>/dev/null | grep -E '^(FASTRTPS_DEFAULT_PROFILES_FILE|ROS_DISCOVERY_SERVER|ROS_DOMAIN_ID)=' | sort | tr '\n' ' '; echo
done | sort | uniq -c | sort -rn | head -10
sec "tmux 会话与窗口名"
tmux list-windows -a -F '#{session_name}:#{window_index} #{window_name}' 2>/dev/null | head -40

sec "复制 data_collection_node 的环境"
pat='^(ROS_|RMW_|FASTRTPS|FASTDDS|CYCLONEDDS|RCUTILS_|DDS)'
src=$(pgrep -u "$(id -u)" -f 'data_collection_node' | tail -1)
[ -n "$src" ] || src=$(pgrep -u "$(id -u)" -f 'HDAS/HDAS' | head -1)
[ -n "$src" ] || { echo "ROS 栈没在跑，退出"; exit 0; }
while IFS= read -r line; do export "$line"; done < <({ tr '\0' '\n' < "/proc/$src/environ"; } 2>/dev/null \
  | grep -E '^(PATH|PYTHONPATH|LD_LIBRARY_PATH|AMENT_PREFIX_PATH|CMAKE_PREFIX_PATH|COLCON_PREFIX_PATH)='; \
  { tr '\0' '\n' < "/proc/$src/environ"; } 2>/dev/null | grep -E "$pat" | grep -v '^ROS_LOG_DIR')
echo "环境取自 pid=$src"

try() { # $1=说明
  sec "$1：节点"
  timeout 20 ros2 node list --no-daemon --spin-time 8 2>&1 | grep -v '^\[' | head -40
  sec "$1：话题个数与头部、关节话题"
  timeout 20 ros2 topic list --no-daemon --spin-time 8 2>/dev/null > "$tmp/topics.txt"
  echo "话题数 $(wc -l < "$tmp/topics.txt")"
  grep -E 'camera_head|feedback_arm|motion_target/target_joint' "$tmp/topics.txt" | head -10
}

# A：节点原样的环境（XML 指向 10.42.0.238）
try "A 节点原样环境（发现服务器 10.42.0.238）"

# B：同一份 XML，只把发现服务器地址换成本机（只在临时目录里改副本，不碰原文件）
sed -E 's#<address>[^<]*</address>#<address>127.0.0.1</address>#' "$xml" > "$tmp/local.xml"
export FASTRTPS_DEFAULT_PROFILES_FILE="$tmp/local.xml"
try "B 副本改成本机 127.0.0.1（看谁在登记处报到了）"
echo "结束 $(date -Is)"
