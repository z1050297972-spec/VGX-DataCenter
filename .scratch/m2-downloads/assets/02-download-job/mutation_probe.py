"""m2-02 变异抽查：只抽关键行为（spec「测试范围」）。每个变异改一处，跑本票测试，必须失败；改完立即还原。"""
import subprocess, sys
from pathlib import Path

WT = Path(sys.argv[1])
JOB = WT / "src/rdp/jobs/downloads/job.py"
ADP = WT / "src/rdp/jobs/downloads/adapters.py"
TEST = "tests/jobs/downloads/test_job.py"
MUTANTS = [
    (JOB, "拒绝 huggingface.co", 'or host == "huggingface.co"', "or False"),
    (JOB, "拒绝 huggingface.co 子域", 'or host.endswith(".huggingface.co")', "or False"),
    (JOB, "跳数上限", "for hop in range(MAX_REDIRECT_HOPS + 1):", "for hop in range(100):"),
    (JOB, "周期复探", "if now - self.last_probe >= MIRROR_RECHECK_INTERVAL_S:", "if False:"),
    (JOB, "续跑跳过已完成文件", "and self.dependencies.verifier.verify(target, file)", "and False"),
    (JOB, "权重目标不覆盖", "os.fsencode(target), 1)", "os.fsencode(target), 0)"),
    (ADP, "token 不发往非镜像", "if urlsplit(url).netloc != urlsplit(MIRROR_ENDPOINT).netloc:", "if False:"),
    (ADP, "aria2 sha256 校验", 'options["checksum"] = f"sha-256={file.lfs_sha256}"', "pass"),
    (ADP, "运行中改并发", 'options["max-concurrent-downloads"] = str(adjustment.max_concurrent_downloads)', "pass"),
    (ADP, "取消先 forceRemove", 'self._send("aria2.forceRemove", [gid])', "pass"),
    (ADP, "curl 限速", '"--limit-rate"', '"--speed-limit"'),
]
for path, name, old, new in MUTANTS:
    orig = path.read_text()
    n = orig.count(old)
    if n != 1:
        print(f"跳过（匹配 {n} 处）：{name}"); continue
    path.write_text(orig.replace(old, new))
    try:
        r = subprocess.run([str(WT / ".venv/bin/pytest"), "-q", "-x", "-p", "no:cacheprovider", TEST], cwd=WT, capture_output=True, text=True, timeout=600)
        print(("被抓住" if r.returncode != 0 else "漏网") + f"：{name}")
    finally:
        path.write_text(orig)
