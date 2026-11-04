import os, pty, sys, time
pw = sys.argv[1]; cmd = sys.argv[2:]
pid, fd = pty.fork()
if pid == 0:
    os.execvp(cmd[0], cmd)
out = b""; sent = 0
while True:
    try: chunk = os.read(fd, 4096)
    except OSError: break
    if not chunk: break
    out += chunk
    hits = out.count("口令".encode()) + out.count("密码".encode())  # M0 第 14 张起提示改叫"密码"
    if sent < 2 and hits > sent:
        time.sleep(0.2); os.write(fd, (pw + "\n").encode()); sent += 1
_, st = os.waitpid(pid, 0)
sys.stdout.write(out.decode(errors="replace")); print("exit=", os.waitstatus_to_exitcode(st))
