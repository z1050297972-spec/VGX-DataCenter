"""m2-01 变异抽查：每个变异改 plan.py 一处，跑本票测试，必须失败；改完立即还原。"""
import subprocess, sys
from pathlib import Path

WT = Path(sys.argv[1])
SRC = WT / "src/rdp/jobs/downloads/plan.py"
TEST = "tests/jobs/downloads/test_plan.py"
MUTANTS = [
    ("探测：3xx 不判失败", "if 300 <= response.status < 400:", "if 300 <= response.status < 300:"),
    ("重试：429 不重试", "if response.status != 429 and not 500", "if True or response.status != 429 and not 500"),
    ("重试：少一次", "for attempt in range(HTTP_MAX_ATTEMPTS):", "for attempt in range(HTTP_MAX_ATTEMPTS - 1):"),
    ("gated 无 token 放行", "if gated and not token:", "if False and gated and not token:"),
    ("disabled 放行", "if disabled:\n", "if False:\n"),
    ("分页：不跟下一页", "return urljoin(current, matches[0]) if matches else None", "return None"),
    ("请求主机不校验", "or target.netloc != _MIRROR_NETLOC", "or False"),
    ("筛选：排除不生效", "and not any(fnmatchcase(item.path, pattern) for pattern in exclude)", "and True"),
    ("筛选：斜杠不补星", "pattern + \"*\" if pattern.endswith(\"/\") else pattern for pattern in request.include", "pattern for pattern in request.include"),
    ("筛选：不排除视频", "and not (request.exclude_video and item.path.startswith(\"videos/\"))", "and True"),
    ("暂存：commit 取 11 位", "/ f\"{parts[1]}@{revision.commit[:12]}\"", "/ f\"{parts[1]}@{revision.commit[:11]}\""),
    ("权重：默认路径错", "return root.path / parts[0] / f\"{parts[1]}@{revision.commit[:12]}\"", "return root.path / parts[1] / f\"{parts[1]}@{revision.commit[:12]}\""),
    ("容量：不计余量", "if available < capacity.remaining_bytes + capacity.reserve_bytes:", "if available < capacity.remaining_bytes:"),
    ("容量：已完整不比大小", "and info.st_size == item.size_bytes:", ":"),
    ("token 不查权限", "or stat.S_IMODE(info.st_mode) != 0o600:", "or False:"),
    ("总时长不限", "deadline = time.monotonic() + HTTP_TOTAL_DEADLINE_S", "deadline = time.monotonic() + 3600"),
    ("响应体上限不查", "if len(raw) > HTTP_MAX_BODY_BYTES:", "if False:"),
    ("数据集填子目录放行", "if request.repo_type == \"dataset\" and request.target_subdir is not None:", "if False:"),
    ("子目录允许 ..", "or part in {\".\", \"..\"}\n        or part != part.strip()", "or False\n        or part != part.strip()"),
    ("子进程非零退出放行", "if child.returncode != 0:", "if False:"),
]
orig = SRC.read_text()
for name, old, new in MUTANTS:
    n = orig.count(old)
    if n != 1:
        print(f"跳过（匹配 {n} 处）：{name}"); continue
    SRC.write_text(orig.replace(old, new))
    try:
        r = subprocess.run([str(WT / ".venv/bin/pytest"), "-q", "-x", "-p", "no:cacheprovider", TEST], cwd=WT, capture_output=True, text=True, timeout=300)
        print(("被抓住" if r.returncode != 0 else "漏网") + f"：{name}")
    finally:
        SRC.write_text(orig)
