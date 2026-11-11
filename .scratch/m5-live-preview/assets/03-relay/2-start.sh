# M5 演练第 2 步：自检后后台启动。只写 ~/rdp_viz/；厂商 XML 只读；不碰厂商进程。
set -euo pipefail
R=$HOME/rdp_viz; B=$R/relay/de2a162e085b094e
cd "$R"
exec 9>run/lock; flock -w 5 9
# 厂商 XML 的副本：发现服务器地址换成本机（eth1 断开时也能报到，0014）。
sed -E 's#<address>[^<]*</address>#<address>127.0.0.1</address>#g' /opt/galaxea/find_server/super_client_profile.xml > fastdds_local.xml.tmp
n=$(grep -c '<address>127.0.0.1</address>' fastdds_local.xml.tmp); other=$(grep '<address>' fastdds_local.xml.tmp | grep -vc '127.0.0.1' || true)
echo "XML 副本：127.0.0.1 $n 处，其他地址 $other 处"; [ "$n" -ge 1 ] && [ "$other" -eq 0 ]
mv fastdds_local.xml.tmp fastdds_local.xml
# 干净环境：只放必需变量，再 source ROS；不设 ROS_DOMAIN_ID（厂商进程也没设）。
INNER='set +u; source /opt/ros/humble/setup.bash; export FASTRTPS_DEFAULT_PROFILES_FILE="$0/fastdds_local.xml" ROS_LOCALHOST_ONLY=0 ROS_HOME="$0/ros_home" ROS_LOG_DIR="$0/log/ros" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH="$0/site:$PYTHONPATH"; cd "$1"; shift 2; exec python3 -m viz_relay "$@"'
echo "--- 自检"
env -i HOME="$HOME" USER="$USER" LANG=C.UTF-8 PATH=/usr/bin:/bin bash -c "$INNER" "$R" "$B" _ --self-test --config "$B/config.json"
echo "--- 端口 8765 监听行数：$(ss -Htln 'sport = :8765' | wc -l)"
[ -f log/relay.log ] && mv log/relay.log log/relay.log.1
setsid nohup env -i HOME="$HOME" USER="$USER" LANG=C.UTF-8 PATH=/usr/bin:/bin bash -c "$INNER" "$R" "$B" _ --config "$B/config.json" > log/relay.log 2>&1 < /dev/null &
pid=$!; echo "$pid" > run/relay.pid; echo "pid=$pid"
for i in $(seq 1 40); do
  if grep -q '^RDP_VIZ_READY' log/relay.log; then echo "READY 用时 $((i/2)) 秒"; break; fi
  if ! kill -0 "$pid" 2>/dev/null; then echo "进程已退出"; break; fi
  sleep 0.5
done
head -20 log/relay.log
ps -o pid,pgid,pcpu,rss,etimes,cmd -p "$pid" | cut -c1-160
ss -Htlnp 'sport = :8765'
