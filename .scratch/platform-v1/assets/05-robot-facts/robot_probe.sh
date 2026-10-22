#!/usr/bin/env bash
# 机器人现场事实采集（只读），服务于决策票「两台机器人的事实」。
# 由 collect.sh 远程执行：ssh <目标> 'bash -s -- <kind>' < robot_probe.sh
#
# 只读约束：不写机器人上任何持久位置。
#   - 唯一的写入是 mktemp 建的临时目录（ROS 日志、gstreamer 注册表、hz/bw 中间输出），退出时删除。
#   - ros2 daemon 如果原本没在跑，结束时关掉，让机器人保持原样。
#   - git 只用 --no-optional-locks，避免 status 回写索引。
#   - 订阅话题会让发布端真的发数据，大图像话题会给机器人加一点负载；不要在正式采集时运行。
#
# 整个脚本包在 main 里、最后一行才调用：bash -s 从 stdin 逐行读脚本，包起来才能保证执行前已经读完；
# main 的 stdin 接 /dev/null，防止 ros2 / python 吃掉剩余脚本。

main() {
  local kind=${1:-unknown}
  local tmp
  tmp=$(mktemp -d) || { echo "mktemp 失败"; return 1; }
  trap 'rm -rf "$tmp"' EXIT
  export ROS_LOG_DIR="$tmp/roslog" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
  export GST_REGISTRY="$tmp/gst-registry.bin"
  mkdir -p "$ROS_LOG_DIR"

  sec "开始 kind=$kind"

  # ---------- 身份 ----------
  sec "身份"
  run 'hostname'
  run 'id'
  run 'ip -br link'
  run 'ip -br addr'
  run 'ip route'
  run 'tr -d "\0" < /sys/firmware/devicetree/base/model 2>/dev/null; echo'
  run 'tr -d "\0" < /sys/firmware/devicetree/base/serial-number 2>/dev/null; echo'
  run 'for f in sys_vendor product_name product_version product_serial board_vendor board_name board_serial; do printf "%s=" "$f"; cat "/sys/class/dmi/id/$f" 2>/dev/null || echo "(不可读或不存在)"; done'
  run 'cat /etc/nv_tegra_release 2>/dev/null'
  run 'ss -ltn 2>/dev/null | head -40'
  run 'grep -hiE "^\s*(Port|PasswordAuthentication|PubkeyAuthentication)\b" /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null'
  # 只看文件名和公钥条数，不读私钥
  run 'ls -la ~/.ssh 2>/dev/null; wc -l ~/.ssh/authorized_keys 2>/dev/null'

  # ---------- 网络（机器人侧） ----------
  sec "网络（机器人侧）"
  run 'nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device 2>/dev/null'
  # --rescan no：只读缓存，不触发扫描
  run 'nmcli -t -f ACTIVE,SSID,BSSID,CHAN,FREQ,RATE,SIGNAL,SECURITY device wifi list --rescan no 2>/dev/null | grep "^yes"'
  run 'command -v iw >/dev/null && iw dev'
  run 'for i in /sys/class/net/*; do n=${i##*/}; [ -d "$i/wireless" ] && command -v iw >/dev/null && iw dev "$n" link; done'
  run 'for i in /sys/class/net/*; do printf "%s operstate=%s speed=%s\n" "${i##*/}" "$(cat "$i/operstate" 2>/dev/null)" "$(cat "$i/speed" 2>/dev/null)"; done'

  # ---------- 算力与系统 ----------
  sec "算力与系统"
  run 'uname -a'
  run 'cat /etc/os-release'
  run 'lscpu'
  run 'free -h'
  run 'df -hT -x tmpfs -x devtmpfs -x squashfs -x overlay 2>/dev/null'
  run 'uptime'
  run 'top -bn1 -o %CPU 2>/dev/null | head -30'
  run 'command -v nvidia-smi >/dev/null && nvidia-smi'
  run 'command -v tegrastats >/dev/null && timeout 3 tegrastats --interval 1000'
  # 硬件编码器节点：决定 viz_relay 能不能在机器人上重编码
  run 'ls /dev | grep -iE "nvhost-msenc|nvenc|v4l2-nvenc|video|dri"; ls /dev/dri 2>/dev/null'
  run 'command -v ffmpeg >/dev/null && { ffmpeg -hide_banner -version | head -1; ffmpeg -hide_banner -encoders 2>/dev/null | grep -iE "264|265|hevc|av1|vp9"; }'
  run 'command -v gst-inspect-1.0 >/dev/null && gst-inspect-1.0 2>/dev/null | grep -iE "h264|h265|x264|openh264|nvv4l2|vaapi|enc"'
  run 'python3 --version; ls -d ~/miniconda3/envs/* ~/anaconda3/envs/* ~/miniforge3/envs/* ~/mambaforge/envs/* 2>/dev/null'
  run 'command -v docker >/dev/null && docker ps --format "{{.Names}}\t{{.Image}}\t{{.Status}}" 2>&1 | head -20'

  # ---------- 进程与服务 ----------
  sec "进程与服务"
  run 'ps -eo pid,user,etimes,pcpu,pmem,args --sort=-pcpu | head -45 | cut -c1-300'
  run 'ps -eo pid,user,etimes,args | grep -iE "ros|bridge|record|bag|mcap|collect|lerobot|foxglove|zenoh|camera|hdas|galaxea|autolife|shm" | grep -v grep | cut -c1-300'
  run 'systemctl list-units --type=service --state=running --no-pager --plain 2>/dev/null | head -80'
  run 'systemctl list-unit-files --no-pager --plain 2>/dev/null | grep -iE "ros|robot|collect|lerobot|galaxea|autolife|camera|bridge|hdas"'
  run 'crontab -l 2>&1 | grep -v "^#"'
  run 'tmux ls 2>&1; screen -ls 2>&1'
  # AutoLife 的相机走共享内存 /dev/shm/camera_image_buffer_<名>；只列文件名和大小
  run 'ls -la /dev/shm | head -40'

  # ---------- 时钟 ----------
  sec "时钟"
  run 'timedatectl 2>&1'
  run 'command -v chronyc >/dev/null && { chronyc tracking; chronyc sources; } 2>&1'

  # ---------- ROS 环境 ----------
  probe_ros "$tmp"

  # ---------- 录制产物 ----------
  sec "录制产物：近 60 天的 mcap / rosbag2（按修改时间倒序）"
  local bags
  bags=$(timeout 180 find / -xdev \( -path /proc -o -path /sys -o -path /dev -o -path /run -o -path /snap \) -prune \
    -o -type f \( -name '*.mcap' -o -name '*.db3' \) -mtime -60 -printf '%T@\t%TY-%Tm-%Td %TH:%TM\t%s\t%p\n' 2>/dev/null | sort -rn)
  printf '共 %s 个\n' "$(printf '%s' "$bags" | grep -c .)"
  printf '%s\n' "$bags" | head -25 | cut -f2-
  local newest
  newest=$(printf '%s\n' "$bags" | head -1 | cut -f4)
  if [ -n "$newest" ]; then
    run "ls -la \"$(dirname "$newest")\" | head -30"
    run "cat \"$(dirname "$newest")/metadata.yaml\" 2>/dev/null | head -150"
    run "command -v ros2 >/dev/null && timeout 90 ros2 bag info \"$newest\" 2>&1 | head -120"
  fi
  sec "录制脚本线索（home 下提到 bag record / mcap 的脚本和配置）"
  # 跳过隐藏目录和包缓存，否则结果会被 conda/pip 缓存刷屏
  run 'timeout 90 grep -rIlE "ros2 bag record|rosbag2_py|bag record|storage.*mcap|\.mcap" --include=*.sh --include=*.py --include=*.yaml --include=*.yml --exclude-dir=".*" --exclude-dir=site-packages --exclude-dir=node_modules --exclude-dir=pkgs --exclude-dir=build --exclude-dir=log ~ 2>/dev/null | head -30'

  # ---------- 自写采集器与 LeRobot 样本 ----------
  sec "采集器部署（CB_Autolife_Data_Collector）"
  local dirs d
  dirs=$(timeout 120 find / -xdev \( -path /proc -o -path /sys -o -path /dev -o -path /run -o -path /snap \) -prune \
    -o -type d \( -iname '*autolife*collect*' -o -iname 'CB_Autolife*' \) -print 2>/dev/null)
  printf '%s\n' "${dirs:-（未找到）}"
  # 路径可能含空格，逐行读，不用 for 分词
  while IFS= read -r d; do
    [ -n "$d" ] || continue
    run "git --no-optional-locks -C \"$d\" log -1 --format='%H %ci %s' 2>&1"
    run "git -C \"$d\" remote -v 2>&1"
    run "git --no-optional-locks -C \"$d\" status --short 2>&1 | head -20"
    run "ls -la \"$d\" | head -50"
  done <<< "$dirs"
  run 'pgrep -af "shm_camera_topic_bridge|record_lerobot|start_lerobot" 2>&1'
  sec "Python 环境里的 lerobot 版本"
  local py
  for py in ~/miniconda3/envs/*/bin/python ~/anaconda3/envs/*/bin/python ~/miniforge3/envs/*/bin/python \
            ~/mambaforge/envs/*/bin/python ~/.venv/bin/python /usr/bin/python3; do
    [ -x "$py" ] || continue
    printf '%s: %s\n' "$py" "$("$py" -c 'import importlib.metadata as m; print(m.version("lerobot"))' 2>&1 | tail -1)"
  done
  while IFS= read -r d; do
    [ -n "$d" ] || continue
    for py in "$d"/.venv/bin/python "$d"/venv/bin/python; do
      [ -x "$py" ] && printf '%s: %s\n' "$py" "$("$py" -c 'import importlib.metadata as m; print(m.version("lerobot"))' 2>&1 | tail -1)"
    done
  done <<< "$dirs"

  sec "LeRobot 数据集样本（最新 5 份 meta/info.json）"
  local infos f
  infos=$(timeout 180 find / -xdev \( -path /proc -o -path /sys -o -path /dev -o -path /run -o -path /snap \) -prune \
    -o -type f -path '*/meta/info.json' -printf '%T@\t%p\n' 2>/dev/null | sort -rn)
  printf '共 %s 份\n' "$(printf '%s' "$infos" | grep -c .)"
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    python3 - "$f" <<'PY'
import json, os, sys, time
p = sys.argv[1]
root = os.path.dirname(os.path.dirname(p))
print("\n--- root:", root, " mtime:", time.strftime("%F %T", time.localtime(os.path.getmtime(p))))
d = json.load(open(p))
for k in ("codebase_version", "robot_type", "fps", "total_episodes", "total_frames", "total_tasks",
          "chunks_size", "data_files_size_in_mb", "video_files_size_in_mb", "data_path", "video_path"):
    if k in d:
        print(f"  {k}: {d[k]}")
for name, feat in d.get("features", {}).items():
    info = feat.get("info") or {}
    vi = {k: v for k, v in info.items() if k.startswith("video.")}
    names = feat.get("names")
    n = len(names) if isinstance(names, list) else names
    print(f"  feature {name}: dtype={feat.get('dtype')} shape={feat.get('shape')} names={n} {vi if vi else ''}")
meta = os.path.join(root, "meta")
print("  meta/:", sorted(os.listdir(meta)))
print("  root/:", sorted(os.listdir(root)))
PY
  done <<< "$(printf '%s\n' "$infos" | head -5 | cut -f2)"

  # ---------- 收尾 ----------
  if [ "${ROS_DAEMON_WAS_RUNNING:-yes}" = no ] && command -v ros2 >/dev/null; then
    sec "关闭本脚本启动的 ros2 daemon"
    run 'ros2 daemon stop'
  fi
  sec "结束"
}

# ROS 运行环境与话题。单独成函数，避免 main 过长。
probe_ros() {
  local tmp=$1
  sec "ROS 运行环境（取自正在运行的 ROS 进程，只打印 ROS/DDS 相关变量）"
  local p e key ament="" best_len=0
  declare -A seen=()
  for p in $(pgrep -u "$(id -u)"); do
    [ "$p" = "$$" ] && continue
    # 外层花括号让"无权限读 environ"的报错也被吞掉（重定向失败发生在 tr 启动之前）
    e=$( { tr '\0' '\n' < "/proc/$p/environ"; } 2>/dev/null ) || continue
    case "$e" in *AMENT_PREFIX_PATH=*) ;; *) continue ;; esac
    key=$(printf '%s\n' "$e" | grep -E '^(ROS_DISTRO|ROS_DOMAIN_ID|RMW_IMPLEMENTATION|ROS_LOCALHOST_ONLY|ROS_AUTOMATIC_DISCOVERY_RANGE|ROS_STATIC_PEERS|CYCLONEDDS_URI|FASTRTPS_DEFAULT_PROFILES_FILE|FASTDDS_DEFAULT_PROFILES_FILE|ZENOH_[A-Z_]*)=' | sort | tr '\n' ' ')
    if [ -z "${seen[$key]+x}" ]; then
      seen[$key]=1
      printf 'pid=%s cmd=%s\n  %s\n' "$p" "$(tr '\0' ' ' < "/proc/$p/cmdline" | cut -c1-200)" "${key:-（无 ROS 变量）}"
    fi
    # 取 AMENT_PREFIX_PATH 最长的那个进程当作"完整环境"的样本
    local a
    a=$(printf '%s\n' "$e" | sed -n 's/^AMENT_PREFIX_PATH=//p')
    if [ "${#a}" -gt "$best_len" ]; then best_len=${#a}; ament=$a; NODE_ENV=$e; fi
  done
  [ -z "$ament" ] && echo "（当前用户下没有读到带 AMENT_PREFIX_PATH 的进程；ROS 栈可能以 root 或其他用户运行，或尚未启动）"
  [ -n "$ament" ] && printf '样本 AMENT_PREFIX_PATH:\n%s\n' "$(printf '%s' "$ament" | tr ':' '\n')"

  sec "复现 ROS 环境：~/.bashrc 里的 ROS 相关行 + 运行中节点的变量"
  run 'grep -nE "^\s*(source|\.)\s+\S*setup\.(bash|sh)|^\s*export\s+(ROS_|RMW_|CYCLONEDDS_|FASTRTPS_|FASTDDS_|ZENOH_)" ~/.bashrc 2>/dev/null'
  local line
  while IFS= read -r line; do
    eval "$line" >/dev/null 2>&1
  done < <(grep -E '^\s*(source|\.)\s+\S*setup\.(bash|sh)|^\s*export\s+(ROS_|RMW_|CYCLONEDDS_|FASTRTPS_|FASTDDS_|ZENOH_)' ~/.bashrc 2>/dev/null)
  if [ -n "$ament" ]; then
    # 从运行中节点的 AMENT_PREFIX_PATH 反推工作空间的 setup.bash，底层先 source（路径顺序是 overlay 在前）
    local pref s list=()
    while IFS= read -r pref; do
      for s in "$pref/setup.bash" "$(dirname "$pref")/setup.bash"; do
        [ -f "$s" ] && { list+=("$s"); break; }
      done
    done < <(printf '%s' "$ament" | tr ':' '\n')
    local i last=""
    for ((i=${#list[@]}-1; i>=0; i--)); do
      [ "${list[$i]}" = "$last" ] && continue
      last=${list[$i]}
      # shellcheck disable=SC1090  # 路径来自运行中节点的环境，运行时才知道
      . "$last" >/dev/null 2>&1
    done
    # 运行中节点的通信变量覆盖 bashrc 的值，确保和它在同一个域、同一个 RMW
    while IFS= read -r line; do
      export "$line"
    done < <(printf '%s\n' "$NODE_ENV" | grep -E '^(ROS_DOMAIN_ID|RMW_IMPLEMENTATION|ROS_LOCALHOST_ONLY|ROS_AUTOMATIC_DISCOVERY_RANGE|ROS_STATIC_PEERS|CYCLONEDDS_URI|FASTRTPS_DEFAULT_PROFILES_FILE|FASTDDS_DEFAULT_PROFILES_FILE)=')
  fi
  run 'printenv | grep -E "^(ROS_|RMW_|CYCLONEDDS_|FASTRTPS_|FASTDDS_|ZENOH_)" | grep -v "^ROS_LOG_DIR" | sort'
  run 'ls /opt/ros 2>/dev/null'
  run 'if [ -n "$CYCLONEDDS_URI" ]; then f=${CYCLONEDDS_URI#file://}; if [ -f "$f" ]; then cat "$f"; else echo "$CYCLONEDDS_URI"; fi; fi'
  if ! command -v ros2 >/dev/null; then
    echo "（ros2 不在 PATH 上，跳过话题采集）"
    return 0
  fi

  sec "ros2 daemon 初始状态"
  local st
  st=$(ros2 daemon status 2>&1); echo "$st"
  case "$st" in *"not running"*) ROS_DAEMON_WAS_RUNNING=no ;; *) ROS_DAEMON_WAS_RUNNING=yes ;; esac

  sec "节点与话题"
  run 'ros2 node list --no-daemon --spin-time 5 2>&1'
  local topics
  topics=$(ros2 topic list -t --no-daemon --spin-time 5 2>&1)
  printf '%s\n' "$topics"
  printf '共 %s 个话题\n' "$(printf '%s' "$topics" | grep -c '^/')"
  [ "$(printf '%s' "$topics" | grep -c '^/')" -le 2 ] && echo "（话题几乎为空：多半是 ROS_DOMAIN_ID / RMW 与机器人上的节点不一致，见上面的运行环境）"

  # 只对相机、关节、状态类话题测频率和带宽；其余话题只出现在上面的清单里
  local name type want
  while read -r name type <&3; do
    case "$name" in /*) ;; *) continue ;; esac
    type=${type#[}; type=${type%]}
    want=0
    case "$type" in
      sensor_msgs/msg/Image|sensor_msgs/msg/CompressedImage|sensor_msgs/msg/JointState|std_msgs/msg/String) want=1 ;;
    esac
    printf '%s' "$name" | grep -qiE 'hdas|motion_target|joint|gripper|camera|image|status|arm' && want=1
    case "$name" in /rosout|/parameter_events) want=0 ;; esac
    [ "$want" = 1 ] || continue

    sec "话题 $name [$type]"
    timeout -k 3 10 ros2 topic info -v "$name" 2>&1 \
      | grep -E 'Publisher count|Subscription count|Node name|Node namespace|Endpoint type|Reliability|Durability|History|Depth' | head -40
    # hz 和 bw 并行跑，各自约 5 秒有效窗口（另加 rclpy 启动时间）
    timeout -k 3 8 ros2 topic hz -w 100 "$name" >"$tmp/hz" 2>&1 &
    timeout -k 3 8 ros2 topic bw "$name" >"$tmp/bw" 2>&1 &
    wait
    echo "-- hz（最后一次统计）"; tail -n 2 "$tmp/hz"
    echo "-- bw（最后一次统计）"; tail -n 2 "$tmp/bw"
    echo "-- echo --once"
    case "$type" in
      *Image|*CompressedImage) timeout -k 2 6 ros2 topic echo --once --no-arr "$name" 2>&1 | head -n 25 ;;
      *JointState)             timeout -k 2 6 ros2 topic echo --once --full-length "$name" 2>&1 | head -n 60 ;;
      *String)                 timeout -k 2 6 ros2 topic echo --once --full-length "$name" 2>&1 | head -c 4000; echo ;;
      *)                       timeout -k 2 6 ros2 topic echo --once --no-arr "$name" 2>&1 | head -n 30 ;;
    esac
  done 3< <(printf '%s\n' "$topics")
}

sec() { printf '\n===== %s [%s] =====\n' "$1" "$(date '+%F %T.%3N %z')"; }
run() { printf '\n$ %s\n' "$1"; eval "$1" 2>&1; printf '[rc=%s]\n' "$?"; }

main "$@" </dev/null
