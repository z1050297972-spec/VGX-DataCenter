#!/usr/bin/env bash
# M5：R1 Lite 头部 H.264 实时流只读核对（本机 XML 副本加入 ROS 图）（负责人 2026-11-09 授权"连接到机器人并查看"）。
# 唯一写入：mktemp 临时目录（ROS 日志和一个订阅脚本），结束时删除。不改配置、不发消息、不用 sudo。
# 订阅头部左路 3 秒（BEST_EFFORT），只统计帧结构，不保存图像。
set -u
tmp=$(mktemp -d) || { echo "mktemp 失败"; exit 1; }
trap 'rm -rf "$tmp"' EXIT
export ROS_LOG_DIR="$tmp/roslog" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
mkdir -p "$ROS_LOG_DIR"
sec() { printf '\n===== %s =====\n' "$1"; }

sec "复制节点环境"
pat='^(ROS_|RMW_|FASTRTPS|FASTDDS|CYCLONEDDS|RCUTILS_|DDS)'
src=$(pgrep -u "$(id -u)" -f 'data_collection_node' | tail -1)
[ -n "$src" ] || src=$(pgrep -u "$(id -u)" -f 'HDAS/HDAS' | head -1)
[ -n "$src" ] || { echo "ROS 栈没在跑，退出"; exit 0; }
while IFS= read -r line; do export "$line"; done < <({ tr '\0' '\n' < "/proc/$src/environ"; } 2>/dev/null \
  | grep -E '^(PATH|PYTHONPATH|LD_LIBRARY_PATH|AMENT_PREFIX_PATH|CMAKE_PREFIX_PATH|COLCON_PREFIX_PATH)='; \
  { tr '\0' '\n' < "/proc/$src/environ"; } 2>/dev/null | grep -E "$pat" | grep -v '^ROS_LOG_DIR')
echo "环境取自 pid=$src；FASTRTPS_DEFAULT_PROFILES_FILE=${FASTRTPS_DEFAULT_PROFILES_FILE:-无}；RMW=${RMW_IMPLEMENTATION:-默认}"
python3 -c "import rclpy, sys; print('rclpy 可导入', sys.version.split()[0])" 2>&1 | tail -1

sed -E "s#<address>[^<]*</address>#<address>127.0.0.1</address>#" /opt/galaxea/find_server/super_client_profile.xml > "$tmp/local.xml"
export FASTRTPS_DEFAULT_PROFILES_FILE="$tmp/local.xml"
echo "改用本机 XML 副本（只在临时目录）"
: 
grep -niE 'codec|encod|h264|h265|hevc|profile|gop|bitrate|fps|width|height|format' /config/signal_camera.yaml 2>/dev/null \
  | grep -viE 'key|secret|token|password|ak|sk' | head -30

sec "订阅头部左路（最多等 15 秒，收到后再收 3 秒）"
cat > "$tmp/head.py" <<'PY'
import time, rclpy
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import CompressedImage

TOPIC = "/hdas/camera_head/left_raw/image_raw_color/compressed"

def nals(data: bytes):
    """按 Annex B 起始码切分，返回 (类型, 偏移) 列表。"""
    out, i, n = [], 0, len(data)
    while True:
        j = data.find(b"\x00\x00\x01", i)
        if j < 0 or j + 3 >= n:
            return out
        out.append((data[j + 3] & 0x1F, j + 3))
        i = j + 3

rclpy.init()
node = rclpy.create_node("rdp_m5_head_probe")
qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST, depth=10)
msgs = []
node.create_subscription(CompressedImage, TOPIC, lambda m: msgs.append((time.monotonic(), m)), qos)
end = time.monotonic() + 15.0
while time.monotonic() < end:
    rclpy.spin_once(node, timeout_sec=0.1)
    if msgs and msgs[-1][0] - msgs[0][0] > 3.0:
        break
print("发现/订阅等待结束，用时 %.1f 秒" % (time.monotonic() - end + 15.0))
node.destroy_node(); rclpy.shutdown()

print("收到", len(msgs), "条")
if not msgs:
    raise SystemExit
fmts = sorted({m.format for _, m in msgs}); print("format:", fmts)
print("frame_id:", sorted({m.header.frame_id for _, m in msgs}))
span = msgs[-1][0] - msgs[0][0]
print("接收频率约 %.1f Hz，平均 %.0f 字节" % ((len(msgs) - 1) / span if span else 0, sum(len(m.data) for _, m in msgs) / len(msgs)))
seqs = {}
for _, m in msgs:
    key = tuple(t for t, _ in nals(bytes(m.data)))
    seqs[key] = seqs.get(key, 0) + 1
print("每条消息里的 NAL 类型序列（次数）:")
for k, v in sorted(seqs.items(), key=lambda kv: -kv[1])[:8]:
    print("  ", list(k), v)
first = bytes(msgs[0][1].data)
print("第一条前 32 字节:", first[:32].hex())
for _, m in msgs:
    d = bytes(m.data)
    for t, off in nals(d):
        if t == 7:
            sps = d[off:off + 4]
            print("SPS: profile_idc=%d constraint=0x%02x level_idc=%d → codec avc1.%02x%02x%02x" % (sps[1], sps[2], sps[3], sps[1], sps[2], sps[3]))
            raise SystemExit
print("3 秒内没有 SPS")
PY
timeout 25 python3 "$tmp/head.py" 2>&1 | grep -v '^\[' | tail -25
echo "结束 $(date -Is)"
