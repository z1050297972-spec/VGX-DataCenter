# 所有写入限制在专用目录；锁覆盖查询后的变更，避免启停交错杀错进程。
set -e -o pipefail
umask 077
root="$HOME/rdp_viz"
mkdir -p "$root/run" "$root/log/ros" "$root/ros_home"
exec 9>"$root/run/lock"
flock -w 5 9 || { echo 'RDP_CONTROL_ERROR lock_busy'; exit 1; }
pidfile="$root/run/relay.pid"

alive() {
    # kill -0 也认僵尸；僵尸已经停止，不能继续占满等待期限。
    kill -0 "$pid" 2>/dev/null && [[ $(ps -o stat= -p "$pid") != Z* ]]
}
owned() {
    [[ -f "$pidfile" ]] || return 1
    read -r pid < "$pidfile"
    [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
    alive || return 1
    local -a args
    local module=0 config=0 i
    mapfile -d '' -t args < "/proc/$pid/cmdline" || return 1
    for ((i=0; i<${#args[@]}-1; i++)); do
        [[ "${args[$i]}" != '-m' || "${args[$i+1]}" != 'viz_relay' ]] || module=1
        if [[ "${args[$i]}" == '--config' && "${args[$i+1]}" == "$root"/relay/*/config.json ]]; then
            running_config="${args[$i+1]}"
            config=1
        fi
    done
    # setsid 启动的主进程就是进程组长，只有这种身份才允许发送组信号。
    [[ "$module" == 1 && "$config" == 1 && $(ps -o pgid= -p "$pid" | tr -d ' ') == "$pid" ]]
}
stop_owned() {
    kill -TERM -- "-$pid" 2>/dev/null || true
    # 第 03 张承诺 3 秒退出，平台给 5 秒宽限，超过后回收整组。
    for ((i=0; i<50; i++)); do
        alive || break
        sleep 0.1
    done
    if alive; then kill -KILL -- "-$pid" 2>/dev/null || true; fi
    rm -f -- "$pidfile"
}

report_error() {
    # 只允许第 03 张的封闭错误码离开机器人，原始输出保留在专用日志目录。
    local code
    code=$(sed -nE 's/^RDP_VIZ_ERROR (config_invalid|import_failed|port_in_use|ros_init_failed) .*/\1/p' "$1" | head -n 1)
    printf 'RDP_CONTROL_ERROR %s\n' "${code:-$2}"
}
