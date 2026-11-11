# M5 演练第 4 步：只停 pidfile 里、命令行确认是我们的转发进程；其余不动。
set -u
R=$HOME/rdp_viz; cd "$R"
exec 9>run/lock; flock -w 5 9
pid=$(cat run/relay.pid 2>/dev/null || true)
if [ -n "$pid" ] && tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null | grep -q -- "-m viz_relay --config $R/"; then
  kill -TERM -- "-$pid"
  for i in $(seq 1 10); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
  if kill -0 "$pid" 2>/dev/null; then kill -KILL -- "-$pid"; echo "TERM 5 秒未退出，已 KILL"; else echo "已停止（TERM 后 $((i/2)) 秒内退出）"; fi
else echo "pidfile 指向的不是我们的进程或已不在，不动它"; fi
rm -f run/relay.pid
echo "端口 8765 监听行数：$(ss -Htln 'sport = :8765' | wc -l)"
echo "残留 viz_relay 进程数：$(pgrep -fc -- '-m viz_relay' || true)"
tail -3 log/relay.log | cut -c1-150
echo "--- ~/rdp_viz 内容"; du -sh "$R"; ls "$R"
echo "--- 主目录下 rdp_viz 以外、比安装时间新的文件（深度 2，含厂商自己写的）"
find "$HOME" -maxdepth 2 -newer "$R/wheels" -not -path "$R*" 2>/dev/null | head -15
