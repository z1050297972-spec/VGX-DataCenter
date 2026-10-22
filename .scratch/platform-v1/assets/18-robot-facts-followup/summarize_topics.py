"""把 r1lite_ros.sh 输出里的逐话题块汇总成一行一个话题。"""
import re, sys

text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
blocks = re.split(r"\n(?====== 话题 )", text)
rows = []
for b in blocks:
    m = re.match(r"===== 话题 (\S+) \[(\S+)\]", b)
    if not m:
        continue
    name, typ = m.groups()
    info, _, rest = b.partition("-- hz")
    hz, _, rest = rest.partition("-- bw")
    bw, _, echo = rest.partition("-- echo --once")
    # 发布者：取 PUBLISHER 段的节点名和可靠性
    pubs = re.findall(r"Node name: (\S+)\nNode namespace: (\S+)\nEndpoint type: PUBLISHER\n(?:.*\n)*?  Reliability: (\S+)", info)
    subs = re.findall(r"Node name: (\S+)\nNode namespace: \S+\nEndpoint type: SUBSCRIPTION\n(?:.*\n)*?  Reliability: (\S+)", info)
    rate = re.findall(r"average rate: ([\d.]+)", hz)
    bwm = re.findall(r"([\d.]+ [KMG]?B/s) from (\d+) messages", bw)
    size = re.findall(r"Message size mean: ([\d.]+ [KMG]?B)", bw)
    fields = {}
    for k in ("format", "encoding", "height", "width", "frame_id"):
        mm = re.search(rf"^\s*{k}: (.+)$", echo, re.M)
        if mm:
            fields[k] = mm.group(1).strip()
    pubs_s = ",".join(f"{ns.rstrip('/')}/{n}".replace("//", "/") + f"({r[0]})" for n, ns, r in pubs)
    subs_s = ",".join(f"{n}({r[0]})" for n, r in subs)
    rows.append((name, typ.split("/")[-1], rate[-1] if rate else "-", bwm[-1][0] if bwm else "-",
                 size[-1] if size else "-", pubs_s, subs_s, " ".join(f"{k}={v}" for k, v in fields.items() if k != "frame_id")))
for r in rows:
    print(" | ".join(r))
print(len(rows), "topics measured", file=sys.stderr)
