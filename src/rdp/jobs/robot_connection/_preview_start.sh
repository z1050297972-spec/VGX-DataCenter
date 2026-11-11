# 先辨认已运行包，再看端口，自己的监听不能误判成外部占用。
if owned; then
    if [[ "$running_config" == "$config" ]]; then
        echo 'RDP_CONTROL running'
    else
        echo 'RDP_CONTROL old_package'
    fi
else
    rm -f -- "$pidfile"
    if ss -Hltn | awk '{sub(/^.*:/, "", $4); print $4}' | grep -Fx -- "$port" >/dev/null; then
        echo 'RDP_CONTROL_ERROR port_in_use'
        exit 1
    fi
    # 日志每次只留上一份，防止 READY 误用上一次启动的记录。
    if [[ -f "$root/log/relay.log" ]]; then mv -f -- "$root/log/relay.log" "$root/log/relay.log.1"; fi
    cd -- "$package"
    started=0
    cleanup() {
        # 启动没有确认成功时回收刚建的进程组；正常成功则保留给人工停止。
        if [[ "$started" == 0 ]]; then stop_owned; fi
    }
    setsid nohup env -i HOME="$HOME" USER="$USER" LANG=C.UTF-8 PATH=/usr/bin:/bin \
        bash -c "$launch" -- "$config" </dev/null >"$root/log/relay.log" 2>&1 9>&- &
    pid=$!
    printf '%s\n' "$pid" > "$pidfile"
    trap cleanup EXIT
    trap 'exit 1' HUP INT TERM
    # 上限 20 秒；worker 另用单调时钟限制本段 30 秒并响应取消。
    for ((i=0; i<200; i++)); do
        if ! alive; then break; fi
        if grep -Fx -- "RDP_VIZ_READY port=$port" "$root/log/relay.log" >/dev/null; then
            started=1
            break
        fi
        sleep 0.1
    done
    if [[ "$started" == 0 ]]; then
        report_error "$root/log/relay.log" ready_timeout
        exit 1
    fi
    trap - EXIT HUP INT TERM
    running_config="$config"
    echo 'RDP_CONTROL started'
fi
# 仅清理专用 relay 根内的历史目录，同时保留本次包和仍在运行的旧包。
for old in "$root"/relay/*; do
    [[ ! -d "$old" || "$old" == "$package" || "$old/config.json" == "$running_config" ]] || rm -rf -- "$old"
done
