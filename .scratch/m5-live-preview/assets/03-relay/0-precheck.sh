# M5 演练第 0 步（只读）：就绪条件、Python/venv、端口、磁盘、负载、已有安装、厂商 XML。
set -u
sec() { printf '\n===== %s =====\n' "$1"; }
sec 时间与负载; date -Is; uptime
sec 网口; ip -br addr
sec 就绪; echo "11811: $(ss -Huln 'sport = :11811' | wc -l) 行"; for p in 'HDAS/HDAS' signal_camera_node realsense2_camera_node data_collection_node; do echo "$p: $(pgrep -fc "$p")"; done
sec 端口8765; ss -Htlnp 'sport = :8765' 2>/dev/null; echo "监听行数 $(ss -Htln 'sport = :8765' | wc -l)"
sec Python; python3 -V; python3 -c 'import venv, ensurepip; print("venv/ensurepip 可导入")'
sec 工具; command -v flock setsid nohup sha256sum tar
sec 已有安装; ls -la ~/rdp_viz 2>&1 | head; ls -d ~/.cache/pip 2>&1
sec 磁盘与内存; df -h ~ | tail -1; free -h | sed -n 2p
sec 厂商XML; ls -l /opt/galaxea/find_server/super_client_profile.xml; grep -n '<address>' /opt/galaxea/find_server/super_client_profile.xml
sec ROS; ls -l /opt/ros/humble/setup.bash
sec tmux会话; tmux list-sessions -F '#{session_name} created=#{t:session_created}' 2>/dev/null
