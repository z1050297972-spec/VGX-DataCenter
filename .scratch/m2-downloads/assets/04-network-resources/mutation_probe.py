"""m2-04 变异抽查：只抽关键行为。"""
import subprocess, sys
from pathlib import Path
WT = Path(sys.argv[1]); M = WT / "src/rdp/monitoring"
TESTS = ["tests/test_monitoring_api.py", "tests/test_monitoring_mirror.py", "tests/test_resource_sampling.py"]
MUTANTS = [
    (M/"vpn.py", "TUN 网卡判开", '"on" if any(p.name.startswith(TUN_PREFIXES) for p in interfaces.iterdir()) else "off"', '"off"'),
    (M/"vpn.py", "代理进程判开", "if PROXY_PROCESSES.intersection(processes)", "if False"),
    (M/"vpn.py", "代理变量判开", 'proxy_status = "on" if values else "off"', 'proxy_status = "off"'),
    (M/"vpn.py", "代理变量去掉口令", "host, port = parsed.hostname, parsed.port", "host, port = parsed.netloc, None"),
    (M/"proc.py", "网速按时间算", "(rx - before.network[name][0]) / elapsed", "(rx - before.network[name][0])"),
    (M/"mirror.py", "308 判不生效", '"ineffective"\n            if any', '"unknown"\n            if any'),
]
for path, name, old, new in MUTANTS:
    orig = path.read_text(); n = orig.count(old)
    if n != 1: print(f"跳过（匹配 {n} 处）：{name}"); continue
    path.write_text(orig.replace(old, new))
    try:
        r = subprocess.run([str(WT/".venv/bin/pytest"), "-q", "-x", "-p", "no:cacheprovider", *TESTS], cwd=WT, capture_output=True, text=True, timeout=600)
        print(("被抓住" if r.returncode else "漏网") + f"：{name}")
    finally:
        path.write_text(orig)
