#!/usr/bin/env bash
# M5：只读列出相机相关话题名和类型（本机 XML 副本加入 ROS 图，不订阅任何话题）。
set -u
tmp=$(mktemp -d) || exit 1
trap 'rm -rf "$tmp"' EXIT
export ROS_LOG_DIR="$tmp/roslog" PYTHONDONTWRITEBYTECODE=1; mkdir -p "$ROS_LOG_DIR"
src=$(pgrep -u "$(id -u)" -f 'data_collection_node' | tail -1)
[ -n "$src" ] || { echo "ROS 栈没在跑"; exit 0; }
while IFS= read -r line; do export "$line"; done < <(tr '\0' '\n' < "/proc/$src/environ" 2>/dev/null | grep -E '^(PATH|PYTHONPATH|LD_LIBRARY_PATH|AMENT_PREFIX_PATH|CMAKE_PREFIX_PATH|COLCON_PREFIX_PATH|ROS_|RMW_|FASTRTPS|FASTDDS)=' | grep -v '^ROS_LOG_DIR')
sed -E 's#<address>[^<]*</address>#<address>127.0.0.1</address>#' /opt/galaxea/find_server/super_client_profile.xml > "$tmp/local.xml"
export FASTRTPS_DEFAULT_PROFILES_FILE="$tmp/local.xml"
date -Is
timeout 25 ros2 topic list -t --no-daemon --spin-time 8 2>/dev/null | grep -iE 'camera|rgb|image|compressed' 
