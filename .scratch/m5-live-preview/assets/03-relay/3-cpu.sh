# M5 演练第 3 步（只读）：采样转发进程 60 秒的 CPU、内存和整机负载。
set -u
pid=$(cat ~/rdp_viz/run/relay.pid); hz=$(getconf CLK_TCK)
t() { awk '{print $14+$15}' /proc/$pid/stat; }
a=$(t); s=$(date +%s.%N); uptime
sleep 60
b=$(t); e=$(date +%s.%N); uptime
awk -v a=$a -v b=$b -v s=$s -v e=$e -v hz=$hz 'BEGIN{printf "转发进程 60 秒平均 CPU：%.1f%%（单核为 100%%）\n", (b-a)/hz/(e-s)*100}'
ps -o pid,pcpu,rss,nlwp,etimes -p $pid
top -b -n 1 -o %CPU | sed -n 7,16p | cut -c1-110
