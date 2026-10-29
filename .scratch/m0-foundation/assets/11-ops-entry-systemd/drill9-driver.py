"""验收 9：在 pty 里驱动 setup.sh 的问答，记录全部终端输出。

用法：python3 -I drill9-driver.py <日志> <导航层目录> <端口> <管理员口令> -- <命令...>
看到健康结果和访问地址后，运行浏览器演练（环境变量 DRILL_BROWSER 给出命令），
然后向 setup.sh 发 SIGINT，等它退出并记录退出码。
"""

import os
import pty
import re
import signal
import subprocess
import sys
import time

log_path, nav, port, password = sys.argv[1:5]
command = sys.argv[sys.argv.index("--") + 1 :]
log = open(log_path, "w", encoding="utf-8")
pid, fd = pty.fork()
if pid == 0:
    os.execvp(command[0], command)

buffer = ""
answered: set[str] = set()
password_count = 0
browser_done = False
deadline = time.monotonic() + 3600


def send(text: str) -> None:
    time.sleep(0.2)
    os.write(fd, (text + "\n").encode())


def root_indices(text: str) -> str:
    indices = []
    for line in text.splitlines():
        match = re.match(r"\s*(\d+) (/mnt/dataset[12]) ext4 ", line)
        if match:
            indices.append(match.group(1))
    return ",".join(indices)


while time.monotonic() < deadline:
    try:
        chunk = os.read(fd, 65536)
    except OSError:
        break
    if not chunk:
        break
    text = chunk.decode(errors="replace")
    log.write(text)
    log.flush()
    buffer += re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    prompts = [
        ("监听地址", "127.0.0.1"),
        ("端口 [", port),
        ("导航层绝对目录", nav),
        ("状态目录 [", ""),
        ("选择GPU编号", "0,1"),
        ("管理员登录名", ""),
        ("管理员显示名", ""),
    ]
    for key, answer in prompts:
        if key in buffer and key not in answered:
            answered.add(key)
            send(answer)
    if "选择存储根编号" in buffer and "roots" not in answered:
        answered.add("roots")
        chosen = root_indices(buffer)
        log.write(f"\n[驱动] 选择存储根 {chosen}\n")
        send(chosen)
    for match in re.finditer(r"存储根(\d+)的名字：", buffer):
        key = "name" + match.group(1)
        if key not in answered:
            answered.add(key)
            row = re.search(rf"^\s*{match.group(1)} /mnt/(dataset[12]) ", buffer, re.M)
            send(row.group(1) if row else "root" + match.group(1))
    while buffer.count("口令") > password_count and password_count < 2:
        password_count += 1
        send(password)
    if "部署健康" in buffer and not browser_done:
        browser_done = True
        browser = os.environ.get("DRILL_BROWSER")
        if browser:
            log.write("\n[驱动] 运行浏览器演练\n")
            result = subprocess.run(browser, shell=True, capture_output=True, text=True, timeout=600)
            log.write(result.stdout + result.stderr + f"[驱动] 浏览器演练退出码 {result.returncode}\n")
        log.write("\n[驱动] 向 setup.sh 发 SIGINT\n")
        log.flush()
        os.kill(pid, signal.SIGINT)

_, status = os.waitpid(pid, 0)
log.write(f"\n[驱动] setup.sh 退出码 {os.waitstatus_to_exitcode(status)}\n")
log.close()
