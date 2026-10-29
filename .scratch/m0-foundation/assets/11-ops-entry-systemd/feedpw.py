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
    if sent < 2 and out.count("口令".encode()) > sent:
        time.sleep(0.2); os.write(fd, (pw + "\n").encode()); sent += 1
_, st = os.waitpid(pid, 0)
sys.stdout.write(out.decode(errors="replace")); print("exit=", os.waitstatus_to_exitcode(st))
