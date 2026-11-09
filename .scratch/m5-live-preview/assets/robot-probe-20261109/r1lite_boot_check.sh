#!/usr/bin/env bash
# M5：负责人执行 boot.sh 之后，核对厂商栈是否重启（只读：ps、tmux 列表、读 boot.sh 和启动脚本开头）。
set -u
sec() { printf '\n===== %s =====\n' "$1"; }
sec "时间"; date -Is; uptime
sec "厂商进程的启动时间（etimes 秒）"
ps -o pid,lstart,etimes,cmd -p "$(pgrep -u "$(id -u)" -d, -f 'fast-discovery-server|HDAS/HDAS|signal_camera_node|realsense2_camera_node|data_collection_node|moca_main_node|homogeneous_controller|rds_ros_monitor_node|ehi_gateway')" 2>/dev/null | cut -c1-140
sec "最近 15 分钟内启动的进程"
ps -u "$(id -u)" -o pid,etimes,cmd --sort=etimes | awk 'NR==1 || $2<900' | grep -vE 'ps -u|awk|bash -s|sshd' | cut -c1-140 | head -30
sec "tmux 会话创建时间"
tmux list-sessions -F '#{session_name} created=#{t:session_created} windows=#{session_windows}' 2>/dev/null
sec "boot.sh"
ls -l ~/boot.sh 2>&1; head -40 ~/boot.sh 2>&1
sec "robot_startup.sh 里对已有会话的处理"
f=/home/nvidia/galaxea/sdk/startup_config/share/startup_config/script/robot_startup.sh
grep -nE 'has-session|kill-session|already|exist|tmux (new|kill|ls)|boot\)|stop\)|restart' "$f" 2>/dev/null | head -30
