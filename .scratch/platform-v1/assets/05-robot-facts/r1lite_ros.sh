#!/usr/bin/env bash
# R1 Lite 实时话题补测（只读），服务于决策票「两台机器人的事实」。
# 背景：ROS 栈在跑（boot.sh 起的 tmux 会话），但 ros2 CLI 一个节点都没发现。
# 第 2 次补测查明：所有节点都带 FASTRTPS_DEFAULT_PROFILES_FILE=/opt/galaxea/find_server/super_client_profile.xml，
# 该 XML 把发现服务器写成 10.42.0.238:11811，而机器人本机没有这个地址；本机的 fast-discovery-server 监听 0.0.0.0:11811。
# 本脚本补读录制配置、启动脚本和各 tmux 窗口的最近日志，再依次尝试几种发现方式，用第一种能看到节点的方式测话题。
# 用法：bash collect.sh r1lite nvidia@<IP> r1lite_ros.sh
#
# 只读约束同 robot_probe.sh：唯一的写入是 mktemp 临时目录；ros2 daemon 原本没在跑的话，结束时关掉。
# 订阅 /compressed 会让发布端真的做 JPEG 压缩，给机器人加一点负载；不要在正式采集时运行。

main() {
  local tmp
  tmp=$(mktemp -d) || { echo "mktemp 失败"; return 1; }
  # 顺序：先关本脚本启动的 daemon，再删临时目录（daemon 的日志在里面）
  trap '[ "${DAEMON_STARTED:-no}" = yes ] && ros2 daemon stop >/dev/null 2>&1; rm -rf "$tmp"' EXIT
  export ROS_LOG_DIR="$tmp/roslog" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
  mkdir -p "$ROS_LOG_DIR"
  local pat='^(ROS_|RMW_|FASTRTPS|FASTDDS|CYCLONEDDS|ZENOH|RCUTILS_|DDS)'
  local sdk=/home/nvidia/galaxea/sdk
  local xml=/opt/galaxea/find_server/super_client_profile.xml

  sec "开始 r1lite_ros（第 3 版）"

  # ---------- 网络与发现服务器 ----------
  sec "网络与发现服务器"
  run 'ip -br addr'
  run 'ip route'
  run "ip route get \$(sed -n 's#.*<address>\\(.*\\)</address>.*#\\1#p' $xml | head -1)"
  # 带进程名，看谁在用 11811（发现服务器）和 7400（SIMPLE 组播发现）
  run "ss -uapn 2>/dev/null | grep -E ':(11811|7400)\\b' | sed -E 's/ +/ /g' | cut -c1-200"
  run 'stat -c "%y %n" ~/.bashrc /opt/galaxea/find_server/super_client_profile.xml'
  run 'sed -n 110,140p ~/.bashrc'

  # ---------- 启动方式 ----------
  sec "启动方式：robot_startup.sh、prestart、会话清单"
  local sc=$sdk/startup_config/share/startup_config
  run "head -120 $sc/script/robot_startup.sh"
  run "cat $sc/script/prestart/prestart_prepare.sh 2>/dev/null | head -80"
  run "ls -la $sc/sessions.d/ATCStandard/R1LITEBody.d/"
  run "for f in $sc/sessions.d/ATCStandard/R1LITEBody.d/*; do echo \"--- \$f\"; head -c 3000 \"\$f\"; echo; done"

  # ---------- 录制与相机配置 ----------
  # 配置里可能有云存储（TOS）的密钥，打印前把疑似敏感字段打码
  sec "录制配置（data_collection config.json，敏感字段已打码）"
  run "ls -la $sdk/data_collection/lib/data_collection/config/"
  redact_dump "$sdk/data_collection/lib/data_collection/config/default/config.json"
  sec "global_params.yaml 的 datacol 段（敏感字段已打码）"
  redact_dump "$sc/config/global_params.yaml" datacol
  sec "头部相机配置 /config/signal_camera.yaml（敏感字段已打码）"
  redact_dump /config/signal_camera.yaml

  # ---------- 节点日志 ----------
  # capture-pane 只把窗口内容打印到 stdout，不改变会话
  sec "各 tmux 窗口最近 25 行（节点日志）"
  local w
  while IFS= read -r w; do
    [ -n "$w" ] || continue
    printf '\n--- %s\n' "$w"
    tmux capture-pane -p -J -t "${w%% *}" -S -200 2>&1 | grep -v '^[[:space:]]*$' | tail -25 | cut -c1-220
  done <<< "$(tmux list-panes -a -F '#{session_name}:#{window_index}.#{pane_index} #{window_name}' 2>/dev/null)"

  # ---------- 复制节点环境 ----------
  # 用 data_collection_node 的环境：它是 Python 节点，PYTHONPATH 里有全部自定义消息包，hz/echo 才能反序列化
  sec "复制节点环境"
  local src line
  src=$(pgrep -u "$(id -u)" -f 'data_collection_node' | tail -1)
  [ -n "$src" ] || src=$(pgrep -u "$(id -u)" -f 'HDAS/HDAS' | head -1)
  if [ -z "$src" ]; then
    echo "（没有找到运行中的 data_collection_node / HDAS，ROS 栈可能没启动，退出）"
    return 0
  fi
  while IFS= read -r line; do
    export "$line"
  done < <({ tr '\0' '\n' < "/proc/$src/environ"; } 2>/dev/null \
    | grep -E '^(PATH|PYTHONPATH|LD_LIBRARY_PATH|AMENT_PREFIX_PATH|CMAKE_PREFIX_PATH|COLCON_PREFIX_PATH)=' ; \
    { tr '\0' '\n' < "/proc/$src/environ"; } 2>/dev/null | grep -E "$pat" | grep -v '^ROS_LOG_DIR')
  printf '环境取自 pid=%s\n' "$src"
  # F 用：同一份 XML，只把发现服务器地址换成本机
  sed -E 's#<address>[^<]*</address>#<address>127.0.0.1</address>#' "$xml" > "$tmp/super_client_local.xml"

  sec "ros2 daemon 初始状态"
  local st
  st=$(ros2 daemon status 2>&1); echo "$st"
  case "$st" in *"not running"*) DAEMON_WAS_RUNNING=no ;; *) DAEMON_WAS_RUNNING=yes ;; esac

  # ---------- 依次尝试发现方式 ----------
  # 每种先在子 shell 里试，成功了再在当前 shell 里设一遍（子 shell 的变量带不出来）
  sec "尝试发现方式（第一种看到 >2 个话题的胜出）"
  TOPICS="" LIST_OPTS="--no-daemon --spin-time 8"
  local s
  for s in A F E C; do
    if ( "setup_$s" "$tmp"; try_list "$s $("desc_$s")" ); then
      "setup_$s" "$tmp"
      try_list "$s $("desc_$s")" >/dev/null && break
    fi
  done
  if [ -z "$TOPICS" ]; then
    # D：经 daemon，用节点原样的环境。原本在跑就直接用，不重启；原本没跑才由本脚本启动，结束时关掉
    if [ "$DAEMON_WAS_RUNNING" = no ]; then
      ros2 daemon start >/dev/null 2>&1 && DAEMON_STARTED=yes
      sleep 5
    fi
    LIST_OPTS="--spin-time 8"
    try_list "D 经 ros2 daemon（节点原样环境）" || true
  fi
  printf '采用：%s\n' "${WINNER:-（全部失败）}"
  if [ -z "$TOPICS" ]; then
    echo "（所有方式都没发现节点，只保留上面的配置和日志供分析）"
    return 0
  fi
  run 'printenv | grep -E "^(ROS_|RMW_|FASTRTPS|FASTDDS)" | grep -v "^ROS_LOG_DIR" | sort'

  sec "节点与话题"
  run "ros2 node list $LIST_OPTS 2>&1"
  printf '%s\n' "$TOPICS"
  printf '共 %s 个话题\n' "$(printf '%s' "$TOPICS" | grep -c '^/')"

  # data_collection_node 订阅的话题 = 原厂录制会录的话题，直接用来对照录制
  local n out
  for n in /data_collection_node /signal_camera /hdas/camera_wrist_left /hdas/camera_wrist_right /HDAS; do
    sec "节点 $n"
    out=$(timeout -k 3 20 ros2 node info $LIST_OPTS "$n" 2>&1)
    # 不确定 Humble 的 node info 是否接受 --spin-time，不接受就去掉它重试
    case "$out" in *"unrecognized arguments"*)
      out=$(timeout -k 3 20 ros2 node info ${LIST_OPTS/--spin-time 8/} "$n" 2>&1) ;;
    esac
    printf '%s\n' "$out" | head -80
  done

  # ---------- 测话题 ----------
  # image_transport 会给每个原始图像挂 theora/compressedDepth/zstd 等插件话题，订阅它们会让发布端现场编码，跳过
  local name type want
  while read -r name type <&3; do
    case "$name" in /*) ;; *) continue ;; esac
    case "$name" in */theora|*/compressedDepth|*/zstd|*/ffmpeg|/rosout|/parameter_events) continue ;; esac
    type=${type#[}; type=${type%]}
    want=0
    case "$type" in
      sensor_msgs/msg/Image|sensor_msgs/msg/CompressedImage|sensor_msgs/msg/JointState|sensor_msgs/msg/Imu) want=1 ;;
    esac
    printf '%s' "$name" | grep -qiE 'hdas|motion_target|motion_control|joint|gripper|camera|image|feedback|controller' && want=1
    [ "$want" = 1 ] || continue

    sec "话题 $name [$type]"
    timeout -k 3 10 ros2 topic info -v "$name" 2>&1 \
      | grep -E 'Publisher count|Subscription count|Node name|Endpoint type|Reliability|Durability|History|Depth' | head -40
    # hz 和 bw 并行跑，各自约 5 秒有效窗口（另加 rclpy 启动时间）
    timeout -k 3 9 ros2 topic hz -w 100 "$name" >"$tmp/hz" 2>&1 &
    timeout -k 3 9 ros2 topic bw "$name" >"$tmp/bw" 2>&1 &
    wait
    echo "-- hz（最后一次统计）"; tail -n 2 "$tmp/hz"
    echo "-- bw（最后一次统计）"; tail -n 2 "$tmp/bw"
    echo "-- echo --once"
    case "$type" in
      *Image|*CompressedImage) timeout -k 2 6 ros2 topic echo --once --no-arr "$name" 2>&1 | head -n 25 ;;
      *JointState)             timeout -k 2 6 ros2 topic echo --once --full-length "$name" 2>&1 | head -n 60 ;;
      *)                       timeout -k 2 6 ros2 topic echo --once --no-arr "$name" 2>&1 | head -n 40 ;;
    esac
  done 3< <(printf '%s\n' "$TOPICS")

  sec "结束"
}

# 发现方式。A：节点原样（XML 指向 10.42.0.238）；F：同一份 XML 改指本机；E：不用发现服务器，普通 SIMPLE 组播发现；
# C：环境变量方式连本机发现服务器（Humble 的 Fast DDS 可能不认 ROS_SUPER_CLIENT，第 2 次补测已失败过一次）
setup_A() { :; }
setup_F() { export FASTRTPS_DEFAULT_PROFILES_FILE="$1/super_client_local.xml"; unset ROS_DISCOVERY_SERVER ROS_SUPER_CLIENT; }
setup_E() { unset FASTRTPS_DEFAULT_PROFILES_FILE ROS_DISCOVERY_SERVER ROS_SUPER_CLIENT; }
setup_C() { unset FASTRTPS_DEFAULT_PROFILES_FILE; export ROS_DISCOVERY_SERVER=127.0.0.1:11811 ROS_SUPER_CLIENT=TRUE; }
desc_A() { echo "节点原样环境（XML 指向 10.42.0.238）"; }
desc_F() { echo "同一份 XML，发现服务器改为 127.0.0.1"; }
desc_E() { echo "不用 XML，SIMPLE 组播发现"; }
desc_C() { echo "不用 XML，ROS_DISCOVERY_SERVER=127.0.0.1:11811 + ROS_SUPER_CLIENT"; }

# 列话题并计数；看到 >2 个（除 /rosout、/parameter_events 之外还有别的）就记下胜出方式
try_list() {
  local out cnt
  out=$(timeout -k 3 25 ros2 topic list -t $LIST_OPTS 2>&1)
  cnt=$(printf '%s\n' "$out" | grep -c '^/')
  printf '[%s] 话题数=%s\n' "$1" "$cnt"
  if [ "$cnt" -gt 2 ]; then TOPICS=$out; WINNER=$1; return 0; fi
  return 1
}

# 打印 JSON/YAML 文件，键名像密钥的值打码；第二个参数给定时只打印该顶层段
redact_dump() {
  [ -f "$1" ] || { echo "（不存在：$1）"; return 0; }
  printf '# %s\n' "$1"
  python3 - "$1" "${2:-}" <<'PY' 2>&1 | head -c 12000
import json, re, sys
path, section = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8").read()
try:
    data = json.loads(text)
except ValueError:
    import yaml
    data = yaml.safe_load(text)
if section:
    data = {section: (data or {}).get(section)}
secret = re.compile(r"(key|secret|token|passw|credential|^ak$|^sk$|auth)", re.I)
def redact(x):
    if isinstance(x, dict):
        return {k: ("***" if secret.search(str(k)) and not isinstance(v, (dict, list)) else redact(v)) for k, v in x.items()}
    if isinstance(x, list):
        return [redact(v) for v in x]
    return x
print(json.dumps(redact(data), ensure_ascii=False, indent=1, default=str))
PY
  echo
}

sec() { printf '\n===== %s [%s] =====\n' "$1" "$(date '+%F %T.%3N %z')"; }
run() { printf '\n$ %s\n' "$1"; eval "$1" 2>&1; printf '[rc=%s]\n' "$?"; }

main "$@" </dev/null
