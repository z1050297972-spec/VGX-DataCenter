"""m2-05 变异抽查：只抽关键行为。"""
import subprocess, sys
from pathlib import Path
WT = Path(sys.argv[1]); D = WT / "src/rdp/jobs/downloads"
TESTS = ["tests/jobs/downloads/test_ingest.py"]
MUTANTS = [
    (D/"_ingest_child.py", "文件大小核对", "if info.st_size != file.size_bytes:", "if False:"),
    (D/"_ingest_child.py", "LeRobot 元信息核对", 'if not isinstance(metadata.get("codebase_version"), str):', "if False:"),
    (D/"ingest.py", "导航写失败退回暂存", '        access("restore", root, stage, target, marker)\n', "        pass\n"),
    (D/"_ingest_build.py", "数据来源=开源下载", '"开源下载", stamp)', '"未知", stamp)'),
    (D/"_ingest_information.py", "14 项：数据格式自动填", '"数据格式": _text(metadata.get("codebase_version")),', '"数据格式": None,'),
    (D/"_ingest_build.py", "入口已存在拒绝", "if (nav / location.path).exists() or (nav / location.path).is_symlink():", "if False:"),
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
